import json
import re
import time
from pathlib import Path

import pytest

import statusline.layout as layout
import statusline.renderer as renderer_mod
import statusline.session as session_mod
import statusline.subagents as subagents_mod
from statusline.config import Config
from statusline.info import SessionView
from statusline.subagents import RunningSubagent
from statusline.text import _visible_width, fmt_tok
from statusline.tokens import TickRecord, TokenLog
from helper import strip_ansi


_r = renderer_mod.Renderer()

SESSION = (Path(__file__).parent.parent / 'claude' / 'statusline'
           / 'session-info-example.json')


def _make_sub(
    agent_type: str = 'general-purpose',
    description: str = 'Draft claude-light Theme literal',
    billed_in: int = 12345,
    output: int = 678,
    first_timestamp: float | None = None,
    model: str = 'claude-sonnet-4-6',
    cache_read_in: int = 0,
    total_input: int = 12345,
    last_activity: tuple = ('tool_use', 'Bash', {'command': 'pytest -q'}),
) -> subagents_mod.RunningSubagent:
    if first_timestamp is None:
        first_timestamp = time.time() - 47
    return subagents_mod.RunningSubagent(
        agent_type      = agent_type,
        description     = description,
        billed_in       = billed_in,
        output          = output,
        first_timestamp = first_timestamp,
        model           = model,
        cache_read_in   = cache_read_in,
        total_input     = total_input,
        last_activity   = last_activity,
    )


# A. subagent_row formatting

def test_subagent_row_includes_agent_type() -> None:
    out = _r.subagent_row(_make_sub(), 100)
    assert 'general-purpose' in strip_ansi(out)


def test_subagent_row_includes_description_when_room() -> None:
    out = _r.subagent_row(_make_sub(), 140)
    assert 'Draft claude-light Theme literal' in strip_ansi(out)


def test_subagent_row_has_marker_glyph() -> None:
    out = _r.subagent_row(_make_sub(), 80)
    assert '▶' in strip_ansi(out)


def test_subagent_row_has_up_arrow() -> None:
    out = _r.subagent_row(_make_sub(), 100)
    assert '↑' in strip_ansi(out)


def test_subagent_row_output_formatted() -> None:
    out = _r.subagent_row(_make_sub(output=678), 100)
    assert '678' in strip_ansi(out)


def test_subagent_row_duration_seconds() -> None:
    out = _r.subagent_row(_make_sub(first_timestamp=time.time() - 47), 100)
    assert '47s' in strip_ansi(out)


@pytest.mark.parametrize('width', [80, 100])
def test_subagent_row_fits_inner_width_narrow(width: int) -> None:
    out = _r.subagent_row(_make_sub(), width)
    assert _visible_width(out) <= width - 3


@pytest.mark.parametrize('width', [120, 160])
def test_subagent_row_fits_inner_width_wide(width: int) -> None:
    line1, line2 = _r.subagent_row(_make_sub(), width).split('\n')
    assert _visible_width(line1) <= width - 3
    assert _visible_width(line2) <= width - 3


def test_subagent_row_long_description_elides() -> None:
    sub = _make_sub(description='x' * 200)
    out = _r.subagent_row(sub, 140)
    assert '…' in strip_ansi(out)


def test_subagent_row_long_description_keeps_agent_type() -> None:
    sub = _make_sub(description='x' * 200)
    out = _r.subagent_row(sub, 80)
    assert 'general-purpose' in strip_ansi(out)


def test_subagent_row_long_agent_type_not_truncated() -> None:
    long_type = 'a-very-unusually-long-agent-type'  # 32 chars
    sub = _make_sub(agent_type=long_type, description='short')
    out = _r.subagent_row(sub, 80)
    assert long_type in strip_ansi(out)


def test_subagent_row_dur_few_seconds() -> None:
    out = _r.subagent_row(_make_sub(first_timestamp=time.time() - 4), 100)
    assert '4s' in strip_ansi(out)


def test_subagent_row_dur_minutes_seconds() -> None:
    out = _r.subagent_row(_make_sub(first_timestamp=time.time() - 83), 100)
    assert '1m23s' in strip_ansi(out)


def test_subagent_row_dur_hours_minutes() -> None:
    out = _r.subagent_row(_make_sub(first_timestamp=time.time() - 3700), 100)
    assert '1h01m' in strip_ansi(out)


def test_subagent_row_dur_no_timestamp_fallback() -> None:
    out = _r.subagent_row(_make_sub(first_timestamp=0), 100)
    assert '0s' in strip_ansi(out)


# B. build_wide integration

def _render_wide(monkeypatch: pytest.MonkeyPatch, subs: list[subagents_mod.RunningSubagent]) -> str:
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=subs)),
    )
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    view    = SessionView(session, Config())
    tick    = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    spec    = layout.build_wide(view, tick, 120, _r)
    return '\n'.join(layout.render_layout(spec, _r))


def test_build_wide_no_subagents_no_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _render_wide(monkeypatch, [])
    assert '▶' not in strip_ansi(out)


def test_build_wide_two_subagents_two_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    sub_a = _make_sub(agent_type='alpha-agent', description='do alpha thing')
    sub_b = _make_sub(agent_type='beta-agent', description='do beta thing')
    out   = _render_wide(monkeypatch, [sub_a, sub_b])
    stripped = strip_ansi(out)
    assert stripped.count('▶') == 2
    assert 'alpha-agent' in stripped
    assert 'beta-agent' in stripped


# C. New behavior — wide two-line shape

def test_subagent_row_wide_has_two_lines() -> None:
    out = _r.subagent_row(_make_sub(), 140)
    assert out.count('\n') == 1


def test_subagent_row_wide_identity_starts_with_marker() -> None:
    line1, _ = _r.subagent_row(_make_sub(), 140).split('\n')
    assert strip_ansi(line1).startswith('▶')


def test_subagent_row_wide_continuation_starts_with_indent() -> None:
    _, line2 = _r.subagent_row(_make_sub(), 140).split('\n')
    assert strip_ansi(line2).startswith('   └')


def test_subagent_row_wide_equal_visible_widths() -> None:
    line1, line2 = _r.subagent_row(_make_sub(), 140).split('\n')
    assert _visible_width(line1) == _visible_width(line2)


def test_subagent_row_wide_continuation_uses_ctx_dim() -> None:
    line1, line2 = _r.subagent_row(_make_sub(), 140).split('\n')
    assert _r.CTX in line1
    assert _r.CTX_DIM in line2
    assert _r.CTX not in line2 or _r.CTX_DIM != _r.CTX


def test_subagent_row_narrow_single_line() -> None:
    out = _r.subagent_row(_make_sub(), 80)
    assert '\n' not in out


def test_subagent_row_narrow_at_boundary() -> None:
    out = _r.subagent_row(_make_sub(), 100)
    assert '\n' not in out


def test_subagent_row_wide_ctx_uses_risk_zone_color() -> None:
    sub_green = _make_sub(total_input=45_000)
    sub_red   = _make_sub(total_input=160_000)
    _, line2_green = _r.subagent_row(sub_green, 140).split('\n')
    _, line2_red   = _r.subagent_row(sub_red,   140).split('\n')
    assert _r.risk_zone_color(45_000) in line2_green
    assert _r.risk_zone_color(160_000) in line2_red


# D. subagent_activity formatter

def test_subagent_activity_bash_extracts_command() -> None:
    act = ('tool_use', 'Bash', {'command': 'pytest -q tests/'})
    out = strip_ansi(_r.subagent_activity(act))
    assert 'Bash[pytest -q tests/]' in out


def test_subagent_activity_read_extracts_basename() -> None:
    act = ('tool_use', 'Read', {'file_path': '/home/x/very/deep/path/file.py'})
    out = strip_ansi(_r.subagent_activity(act))
    assert 'Read[file.py]' in out


def test_subagent_activity_unknown_tool_first_value() -> None:
    act = ('tool_use', 'NovelTool', {'foo': 'bar', 'baz': 'qux'})
    out = strip_ansi(_r.subagent_activity(act))
    assert 'NovelTool[bar]' in out


def test_subagent_activity_long_arg_truncated() -> None:
    act = ('tool_use', 'Bash', {'command': 'x' * 100})
    out = strip_ansi(_r.subagent_activity(act))
    # Extract the arg portion between '[' and ']'
    arg = out.split('[', 1)[1].rstrip(']')
    assert _visible_width(arg) == 37  # 36 chars + ellipsis


def test_subagent_activity_thinking() -> None:
    out = strip_ansi(_r.subagent_activity(('thinking', '', {})))
    assert '(thinking)' in out


def test_subagent_activity_replying() -> None:
    out = strip_ansi(_r.subagent_activity(('text', '', {})))
    assert '(replying)' in out


def test_subagent_activity_empty() -> None:
    assert _r.subagent_activity(('', '', {})) == ''


# E. Burn-metric cluster (tasks 5.1–5.3)

def _make_established_sub(**kwargs) -> RunningSubagent:
    """Subagent running for 60s with enough tokens to produce valid tpm."""
    defaults = dict(
        first_timestamp=time.time() - 60,
        total_input=3000,
        billed_in=3000,
        output=600,
    )
    defaults.update(kwargs)
    return _make_sub(**defaults)


def test_burn_cluster_wide_shows_tpm_and_share() -> None:
    # 5.1: ample wide width — both t/m and % must appear
    sub = _make_established_sub()
    session_inout = sub.total_input + sub.output + 1000  # non-zero denominator
    out = _r.subagent_row(sub, 200, session_inout=session_inout)
    _, line2 = out.split('\n')
    plain = strip_ansi(line2)
    assert 't/m' in plain
    assert '%' in plain


def _pressure_sub() -> RunningSubagent:
    """Wide stat fields + a max-length (36-char) activity, so the narrowest
    wide widths are forced to shed stats. tpm/share both have valid data."""
    return _make_sub(
        billed_in=900_000_000, output=500_000_000, total_input=900_000_000,
        first_timestamp=time.time() - 60, model='claude-sonnet-4-6',
        last_activity=('tool_use', 'Bash', {'command': 'x' * 60}),
    )


def _droppables(line2: str) -> tuple[bool, bool, bool]:
    """(t/m, share%, ↑output) presence in a continuation line."""
    p = strip_ansi(line2)
    return ('t/m' in p, '%' in p, '↑' in p)


def test_burn_cluster_drop_priority_respected() -> None:
    # Stats shed in order share% → ↑output → t/m. So across every width the
    # kept set is a prefix of [t/m, ↑output, share%] from the high-priority end;
    # a lower-priority stat is never present without all higher-priority ones.
    valid = {(True, True, True), (True, False, True), (True, False, False), (False, False, False)}
    sub = _pressure_sub()
    si  = 10 ** 12
    for w in range(101, 201):
        _, line2 = _r.subagent_row(sub, w, session_inout=si).split('\n')
        combo = _droppables(line2)
        assert combo in valid, f'width={w}: out-of-priority cluster {combo}'


def test_burn_cluster_all_drop_levels_reachable() -> None:
    # The chain isn't vacuous: each successive drop level is actually hit.
    sub = _pressure_sub()
    si  = 10 ** 12
    seen = {_droppables(_r.subagent_row(sub, w, session_inout=si).split('\n')[1])
            for w in range(101, 201)}
    assert (True, False, False) in seen   # share + output dropped, t/m kept
    assert (True, False, True)  in seen    # share dropped, output kept
    assert (True, True, True)   in seen    # nothing dropped


def test_burn_cluster_tok_dur_model_never_drop() -> None:
    # Token count, elapsed, and model survive at every width, even under pressure.
    sub = _pressure_sub()
    si  = 10 ** 12
    for w in range(101, 201):
        _, line2 = _r.subagent_row(sub, w, session_inout=si).split('\n')
        plain = strip_ansi(line2)
        assert re.search(r'\d+m\d{2}s', plain), f'width={w} dropped elapsed'
        assert 'sonnet' in plain, f'width={w} dropped model'
        assert fmt_tok(sub.total_input) in plain, f'width={w} dropped token count'


def test_burn_cluster_widening_only_adds_stats() -> None:
    # Monotonic: a wider row never shows fewer droppable stats than a narrower one.
    sub = _pressure_sub()
    si  = 10 ** 12
    prev_count = -1
    for w in range(101, 201):
        _, line2 = _r.subagent_row(sub, w, session_inout=si).split('\n')
        count = sum(_droppables(line2))
        assert count >= prev_count, f'width={w}: stat count dropped on widening'
        prev_count = count


def test_burn_cluster_narrow_row_unchanged() -> None:
    # 5.3: width ≤ 100 — neither figure, single line, row unchanged
    sub = _make_established_sub()
    session_inout = sub.total_input + sub.output + 5000
    for w in [80, 100]:
        out = _r.subagent_row(sub, w, session_inout=session_inout)
        assert '\n' not in out, f'width={w} produced two lines'
        plain = strip_ansi(out)
        assert 't/m' not in plain, f'width={w} showed t/m in narrow row'
        assert '%' not in plain, f'width={w} showed % in narrow row'


# F. Single stat line + cost removal (burndown mockup match)

def test_subagent_row_wide_no_cost() -> None:
    sub = _make_established_sub()
    out = _r.subagent_row(sub, 160, session_inout=sub.total_input + sub.output + 5000)
    assert '$' not in strip_ansi(out)


def test_subagent_row_narrow_no_cost() -> None:
    assert '$' not in strip_ansi(_r.subagent_row(_make_sub(), 100))


def test_subagent_row_wide_dur_and_model_on_continuation() -> None:
    # duration + model relocate from the identity line to the stat cluster
    sub = _make_established_sub(model='claude-sonnet-4-6', first_timestamp=time.time() - 90)
    line1, line2 = _r.subagent_row(
        sub, 160, session_inout=sub.total_input + sub.output + 5000).split('\n')
    p1, p2 = strip_ansi(line1), strip_ansi(line2)
    assert 'sonnet' in p2 and 'sonnet' not in p1
    assert '1m30s' in p2 and '1m30s' not in p1


def test_subagent_row_wide_identity_is_just_type_and_desc() -> None:
    line1, _ = _r.subagent_row(_make_sub(description='hello world'), 160).split('\n')
    assert strip_ansi(line1).rstrip() == '▶  general-purpose · hello world'


def test_subagent_row_wide_share_one_decimal() -> None:
    sub = _make_established_sub()
    _, line2 = _r.subagent_row(
        sub, 200, session_inout=sub.total_input + sub.output + 5000).split('\n')
    m = re.search(r'(\d+\.\d+)%', strip_ansi(line2))
    assert m is not None
    assert len(m.group(1).split('.')[1]) == 1  # exactly one decimal place


def test_subagent_row_wide_model_right_justified() -> None:
    # 5-char model name (haiku) gains a leading space from rjust(6)
    sub = _make_established_sub(model='claude-haiku-4-5', first_timestamp=time.time() - 90)
    _, line2 = _r.subagent_row(
        sub, 200, session_inout=sub.total_input + sub.output + 5000).split('\n')
    assert strip_ansi(line2).rstrip().endswith(' haiku')
