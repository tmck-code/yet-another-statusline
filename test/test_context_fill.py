'''Tests for the context-window fill metric (Audit DATA-1/DATA-2/DATA-3 + CTX-NEG):
input-only, prefers the host's pre-calculated used_percentage, clamped to [0,100].'''
import json

import statusline_command as sl
from statusline.models import ContextWindow, SessionInfo


def _ctx(**kw):
    return ContextWindow.from_dict(kw)


def test_prefers_host_used_percentage_over_manual_calc():
    # Host says 62.5% (input-only). Manual calc would give a different number;
    # the host value must win.
    ctx = _ctx(total_input_tokens=125000, total_output_tokens=8000,
               context_window_size=200000, used_percentage=62.5)
    ratio, pct = sl.context_fill(ctx)
    assert pct == 62.5
    assert abs(ratio - 0.625) < 1e-9


def test_excludes_output_tokens_in_fallback():
    # No host used_percentage -> input-only manual calc. Output (8000) must NOT
    # be added: 125000/200000 = 62.5%, never (125000+8000)/200000 = 66.5%.
    ctx = _ctx(total_input_tokens=125000, total_output_tokens=8000,
               context_window_size=200000)
    ratio, pct = sl.context_fill(ctx)
    assert pct == 62.5
    assert abs(ratio - 0.625) < 1e-9


def test_fallback_uses_soft_limit_when_window_unknown():
    ctx = _ctx(total_input_tokens=75000, total_output_tokens=0, context_window_size=0)
    _, pct = sl.context_fill(ctx)
    assert pct == 50.0  # 75000 / SOFT_LIMIT(150000)


def test_null_used_percentage_falls_back_not_crashes():
    # used_percentage absent (null early / after /compact) -> manual fallback, no crash.
    ctx = _ctx(total_input_tokens=20000, context_window_size=200000)
    assert ctx.used_percentage is None
    _, pct = sl.context_fill(ctx)
    assert pct == 10.0


def test_clamps_negative_and_over_range():
    # CTX-NEG: negative tokens are floored at from_dict; an out-of-range host
    # percentage is clamped in context_fill.
    neg = _ctx(total_input_tokens=-100000, context_window_size=200000)
    assert neg.total_input_tokens == 0
    ratio, pct = sl.context_fill(neg)
    assert ratio == 0.0 and pct == 0.0

    over = ContextWindow(used_percentage=250.0, context_window_size=200000)
    ratio2, pct2 = sl.context_fill(over)
    assert pct2 == 100.0 and ratio2 == 1.0


def test_nan_inf_used_percentage_is_dropped():
    # json.loads accepts NaN/Infinity; they must not reach the bar math.
    ctx = ContextWindow.from_dict(json.loads(
        '{"total_input_tokens": 40000, "context_window_size": 200000, "used_percentage": NaN}'
    ))
    assert ctx.used_percentage is None        # finite-guarded -> None -> fallback
    _, pct = sl.context_fill(ctx)
    assert pct == 20.0


def test_context_line_renders_input_only_percentage():
    # End-to-end through the renderer: a payload whose input-only fill is 25%
    # but whose input+output would be ~29% must show 25%.
    s = SessionInfo.from_dict({
        'context_window': {'total_input_tokens': 50000, 'total_output_tokens': 8000,
                           'context_window_size': 200000},
    })
    r = sl.Renderer(theme=sl.CLAUDE_DARK)
    line = sl.strip_ansi(r.context_line(s.context_window, 76)) if hasattr(sl, 'strip_ansi') else r.context_line(s.context_window, 76)
    import re
    plain = re.sub(r'\x1b\[[0-9;]*m', '', line)
    assert '25%' in plain          # 50000/200000, not 58000/200000 (29%)
    assert '29%' not in plain
