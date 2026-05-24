import json
import time
from pathlib import Path

import pytest

import statusline_command as sl

_r = sl.Renderer()
SESSION = (Path(__file__).parent.parent / 'claude' / 'statusline'
           / 'session-info-example.json')


def _session() -> sl.SessionInfo:
    return sl.SessionInfo.from_dict(json.loads(SESSION.read_text()))


def _make_sub() -> sl.RunningSubagent:
    return sl.RunningSubagent(
        agent_type      = 'Explore',
        description     = 'test desc',
        billed_in       = 1000,
        output          = 100,
        first_timestamp = time.time() - 10,
        model           = 'claude-sonnet-4-6',
        cache_read_in   = 0,
        total_input     = 1000,
        last_activity   = ('tool_use', 'Bash', {'command': 'pytest'}),
    )


def _silence_dynamic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every conditional (dynamic) section so token stats are last."""
    monkeypatch.setattr(sl.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: sl.RunningSubagents(subagents=[])))
    monkeypatch.setattr(sl.TaskList, 'from_session',
                        classmethod(lambda cls, path: sl.TaskList(tasks=[], last_event_ts=0.0)))
    monkeypatch.setattr(sl.LoadedSkills, 'from_transcript',
                        classmethod(lambda cls, path: sl.LoadedSkills(names=[])))
    monkeypatch.setattr(sl.OpenSpec, 'from_cwd',
                        classmethod(lambda cls, cwd: sl.OpenSpec(changes=[])))


def _kinds(spec: sl.LayoutSpec) -> list[str]:
    return [row.kind for row in spec.rows]


def test_seam_present_with_dynamic_section(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(sl.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: sl.RunningSubagents(subagents=[_make_sub()])))
    spec = sl.build_wide(_session(), 140, _r)
    assert _kinds(spec).count('separator_seam') == 1


def test_no_seam_without_dynamic_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    spec = sl.build_wide(_session(), 140, _r)
    assert 'separator_seam' not in _kinds(spec)
    assert _kinds(spec)[-1] == 'bottom_border'


def test_seam_is_first_separator_below_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(sl.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: sl.RunningSubagents(subagents=[_make_sub()])))
    spec = sl.build_wide(_session(), 140, _r)
    seam_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'separator_seam')
    # Seam threads up-elbows into the token-stat vsep columns.
    assert spec.rows[seam_idx].ups
    # The very next row is the dynamic content the seam introduces.
    assert spec.rows[seam_idx + 1].kind == 'content'


def test_seam_renders_solid_not_heavy(monkeypatch: pytest.MonkeyPatch) -> None:
    from helper import strip_ansi
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(sl.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: sl.RunningSubagents(subagents=[_make_sub()])))
    spec = sl.build_wide(_session(), 140, _r)
    seam_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'separator_seam')
    seam = strip_ansi(sl.render_layout(spec, _r)[seam_idx])
    assert seam[0] == '├' and seam[-1] == '┤'   # single-line box ends
    assert '─' in seam and '┴' in seam          # solid rule, up-elbows into token vseps
    assert '━' not in seam and '┷' not in seam  # not the heavy variant


def test_only_first_dynamic_separator_is_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two dynamic sections (skills + subagents): first separator is the seam,
    # the separator between them stays a normal dotted-dim separator.
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(sl.LoadedSkills, 'from_transcript',
                        classmethod(lambda cls, path: sl.LoadedSkills(names=['x:demo'])))
    monkeypatch.setattr(sl.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: sl.RunningSubagents(subagents=[_make_sub()])))
    spec = sl.build_wide(_session(), 140, _r)
    kinds = _kinds(spec)
    assert kinds.count('separator_seam') == 1
    seam_idx = kinds.index('separator_seam')
    # A later separator (between skills and subagents) is normal, not a seam.
    assert 'separator_dim' in kinds[seam_idx + 1:]
