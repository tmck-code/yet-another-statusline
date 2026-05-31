import json
import time
from pathlib import Path

import pytest

import statusline.layout as layout
import statusline.renderer as renderer_mod
import statusline.session as session_mod
import statusline.subagents as subagents_mod
import statusline.tasks as tasks_mod
import statusline.skills as skills_mod
import statusline.openspec as openspec_mod
from statusline.config import Config
from statusline.info import SessionView
from statusline.tokens import TickRecord, TokenLog

_r = renderer_mod.Renderer()
SESSION = (Path(__file__).parent.parent / 'claude' / 'statusline'
           / 'session-info-example.json')


def _session() -> session_mod.SessionInfo:
    return session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))


def _view(session=None) -> SessionView:
    if session is None:
        session = _session()
    return SessionView(session, Config())


def _tick() -> TickRecord:
    return TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)


def _make_sub() -> subagents_mod.RunningSubagent:
    return subagents_mod.RunningSubagent(
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
    """Strip every conditional (dynamic) section so token stats are last.

    Each dynamic section below the token stats reads the real machine (the
    transcript, ~/.claude/settings.json, the cwd's openspec dir, ...). Left
    alone, the host's own plugins/skills/tasks leak in and synthesise a
    dynamic row + seam, so neutralise every source — including
    Workspace.plugins, which reads CLAUDE_DIR/settings.json directly.
    """
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[])))
    monkeypatch.setattr(tasks_mod.TaskList, 'from_session',
                        classmethod(lambda cls, path: tasks_mod.TaskList(tasks=[], last_event_ts=0.0)))
    monkeypatch.setattr(skills_mod.LoadedSkills, 'from_transcript',
                        classmethod(lambda cls, path: skills_mod.LoadedSkills(names=[])))
    monkeypatch.setattr(openspec_mod.OpenSpec, 'from_cwd',
                        classmethod(lambda cls, cwd: openspec_mod.OpenSpec(changes=[])))
    monkeypatch.setattr(session_mod.Workspace, 'plugins', property(lambda self: ''))


def _kinds(spec: layout.LayoutSpec) -> list[str]:
    return [row.kind for row in spec.rows]


def test_seam_present_with_dynamic_section(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    assert _kinds(spec).count('separator_seam') == 1


def test_no_seam_without_dynamic_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    assert 'separator_seam' not in _kinds(spec)
    assert _kinds(spec)[-1] == 'bottom_border'


def test_seam_is_first_separator_below_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    seam_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'separator_seam')
    # Seam threads up-elbows into the token-stat vsep columns.
    assert spec.rows[seam_idx].ups
    # The very next row is the dynamic content the seam introduces.
    assert spec.rows[seam_idx + 1].kind == 'content'


def test_seam_renders_solid_not_heavy(monkeypatch: pytest.MonkeyPatch) -> None:
    from helper import strip_ansi
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    seam_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'separator_seam')
    seam = strip_ansi(layout.render_layout(spec, _r)[seam_idx])
    assert seam[0] == '├' and seam[-1] == '┤'   # single-line box ends
    assert '─' in seam and '┴' in seam          # solid rule, up-elbows into token vseps
    assert '━' not in seam and '┷' not in seam  # not the heavy variant


def test_only_first_dynamic_separator_is_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two dynamic sections (skills + subagents): first separator is the seam,
    # the separator between them stays a normal dotted-dim separator.
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(skills_mod.LoadedSkills, 'from_transcript',
                        classmethod(lambda cls, path: skills_mod.LoadedSkills(names=['x:demo'])))
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    kinds = _kinds(spec)
    assert kinds.count('separator_seam') == 1
    seam_idx = kinds.index('separator_seam')
    # A later separator (between skills and subagents) is normal, not a seam.
    assert 'separator_dim' in kinds[seam_idx + 1:]
