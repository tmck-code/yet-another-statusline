import json
import time
from pathlib import Path

import pytest

import statusline_command as sl
from conftest import strip_ansi


_r = sl.Renderer()

SESSION = (Path(__file__).parent.parent / 'claude' / 'statusline'
           / 'session-info-example.json')


def _make_sub(
    agent_type: str = 'general-purpose',
    description: str = 'Draft claude-light Theme literal',
    billed_in: int = 12345,
    output: int = 678,
    first_timestamp: float | None = None,
) -> sl.RunningSubagent:
    if first_timestamp is None:
        first_timestamp = time.time() - 47
    return sl.RunningSubagent(
        agent_type      = agent_type,
        description     = description,
        billed_in       = billed_in,
        output          = output,
        first_timestamp = first_timestamp,
    )


# ---------------------------------------------------------------------------
# A. subagent_row formatting
# ---------------------------------------------------------------------------

def test_subagent_row_includes_agent_type() -> None:
    out = _r.subagent_row(_make_sub(), 100)
    assert 'general-purpose' in strip_ansi(out)


def test_subagent_row_includes_description_when_room() -> None:
    out = _r.subagent_row(_make_sub(), 100)
    assert 'Draft claude-light Theme literal' in strip_ansi(out)


def test_subagent_row_has_marker_glyph() -> None:
    out = _r.subagent_row(_make_sub(), 100)
    assert '▶' in strip_ansi(out)


def test_subagent_row_has_down_arrow() -> None:
    out = _r.subagent_row(_make_sub(), 100)
    assert '↓' in strip_ansi(out)


def test_subagent_row_has_up_arrow() -> None:
    out = _r.subagent_row(_make_sub(), 100)
    assert '↑' in strip_ansi(out)


def test_subagent_row_billed_in_formatted() -> None:
    out = _r.subagent_row(_make_sub(billed_in=12345), 100)
    assert '12.3K' in strip_ansi(out)


def test_subagent_row_output_formatted() -> None:
    out = _r.subagent_row(_make_sub(output=678), 100)
    assert '678' in strip_ansi(out)


def test_subagent_row_duration_seconds() -> None:
    out = _r.subagent_row(_make_sub(first_timestamp=time.time() - 47), 100)
    assert '47s' in strip_ansi(out)


@pytest.mark.parametrize('width', [80, 100, 160])
def test_subagent_row_fits_inner_width(width: int) -> None:
    out = _r.subagent_row(_make_sub(), width)
    assert sl._visible_width(out) <= width - 3


def test_subagent_row_long_description_elides() -> None:
    sub = _make_sub(description='x' * 200)
    out = _r.subagent_row(sub, 80)
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


# ---------------------------------------------------------------------------
# B. build_wide integration
# ---------------------------------------------------------------------------

def _render_wide(monkeypatch: pytest.MonkeyPatch, subs: list[sl.RunningSubagent]) -> str:
    monkeypatch.setattr(
        sl.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir: sl.RunningSubagents(subagents=subs)),
    )
    session = sl.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    spec    = sl.build_wide(session, 120, _r)
    return '\n'.join(sl.render_layout(spec, _r))


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
