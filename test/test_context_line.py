import re

import statusline_command as sl
from helper import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer
ContextWindow = sl.ContextWindow
CLR_ALERT = sl.CLR_ALERT
SOFT_LIMIT = sl.SOFT_LIMIT


def _pcts(s: str) -> list[int]:
    return [int(m) for m in re.findall(r'(\d+)%', strip_ansi(s))]


def test_context_line_shows_real_window_fill_not_soft_pressure() -> None:
    # Regression for the 524% bug: a large context must read as the real window
    # fill (786.7K / 1M = 79%), never tokens/150K.
    r = Renderer()
    ctx = ContextWindow(total_input_tokens=786_700, total_output_tokens=0, context_window_size=1_000_000)
    out = r.context_line(ctx, 120)
    pcts = _pcts(out)
    assert pcts and max(pcts) <= 100, strip_ansi(out)
    assert '79%' in strip_ansi(out), strip_ansi(out)


def test_context_line_caps_at_100_when_over_window() -> None:
    r = Renderer()
    ctx = ContextWindow(total_input_tokens=1_200_000, total_output_tokens=0, context_window_size=1_000_000)
    out = r.context_line(ctx, 120)
    assert _pcts(out) and max(_pcts(out)) == 100
    assert CLR_ALERT in out   # a full window renders red


def test_context_line_under_soft_limit() -> None:
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=10_000,
        total_output_tokens=5_000,
        context_window_size=200_000,
    )
    available = 76
    out = r.context_line(ctx, available)
    assert _visible_width(out) <= available
    assert CLR_ALERT not in out


def test_context_line_over_soft_limit() -> None:
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=200_000,
        total_output_tokens=0,
        context_window_size=200_000,
    )
    available = 76
    out = r.context_line(ctx, available)
    assert CLR_ALERT in out
    assert _visible_width(out) <= available


def test_context_line_compact_respects_available() -> None:
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=10_000,
        total_output_tokens=5_000,
    )
    available = 30
    out = r.context_line_compact(ctx, available)
    assert _visible_width(out) <= available
