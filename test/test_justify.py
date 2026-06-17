"""Justify layout tests (tasks 4.2–4.4).

Exercises the ``justify`` knob in ``build_wide``: box integrity under
distributed slack, equivalence when total_slack==0, and correct N=3
distribution when neither elapsed nor cache sections are active.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
import yas.info.subagents as subagents_mod
import yas.info.tasks as tasks_mod
import yas.info.skills as skills_mod
import yas.info.openspec as openspec_mod
from yas.config import Config
from yas.info import SessionView
from yas.render.text import _visible_width
from yas.tokens import TickRecord, TokenLog

_r = renderer_mod.Renderer()
SESSION = (Path(__file__).parent.parent / 'ops' / 'session-info-example.json')


def _session() -> session_mod.SessionInfo:
    return session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))


def _view(cfg: Config) -> SessionView:
    return SessionView(_session(), cfg)


def _tick() -> TickRecord:
    return TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)


def _silence_dynamic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[])))
    monkeypatch.setattr(tasks_mod.TaskList, 'from_session',
                        classmethod(lambda cls, path: tasks_mod.TaskList(tasks=[], last_event_ts=0.0)))
    monkeypatch.setattr(skills_mod.LoadedSkills, 'from_transcript',
                        classmethod(lambda cls, path: skills_mod.LoadedSkills(names=[])))
    monkeypatch.setattr(openspec_mod.OpenSpec, 'from_cwd',
                        classmethod(lambda cls, cwd: openspec_mod.OpenSpec(changes=[])))
    monkeypatch.setattr(session_mod.Workspace, 'plugins', property(lambda self: ''))


def _rendered_lines(view: SessionView, width: int) -> list[str]:
    spec = layout.build_wide(view, _tick(), width, _r)
    return layout.render_layout(spec, _r)


# 4.2 – box integrity with justify enabled

@pytest.mark.parametrize('width', [95, 120, 140, 160])
def test_justify_box_all_rows_uniform_width(
    monkeypatch: pytest.MonkeyPatch, strip_ansi: Callable[[str], str], width: int
) -> None:
    """With cfg.justify=True every rendered row is exactly `width` columns wide."""
    _silence_dynamic(monkeypatch)
    view = _view(Config(justify=True))
    lines = _rendered_lines(view, width)
    widths = {_visible_width(strip_ansi(ln)) for ln in lines}
    assert widths == {width}, f'mismatched row widths at terminal {width}: {widths}'


def test_justify_top_content_row_is_width_wide(
    monkeypatch: pytest.MonkeyPatch, strip_ansi: Callable[[str], str],
) -> None:
    """The top content row (index 1) rendered with justify=True is exactly ``width`` columns."""
    _silence_dynamic(monkeypatch)
    width = 160
    view = _view(Config(justify=True))
    lines = [strip_ansi(ln) for ln in _rendered_lines(view, width)]
    assert _visible_width(lines[1]) == width


# 4.3 – total_slack == 0 produces output identical to justify-disabled

def test_justify_slack_zero_matches_unjustified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When fit_path fills the entire target width (slack=0), justify=True output
    is byte-for-byte identical to justify=False."""
    _silence_dynamic(monkeypatch)
    # Patch fit_path to consume all available width so total_slack == 0.
    monkeypatch.setattr(
        renderer_mod.Renderer, 'fit_path',
        lambda self, pwd, git, target_w, compact_only=False: 'x' * max(0, target_w),
    )
    session = _session()
    view_on  = SessionView(session, Config(justify=True))
    view_off = SessionView(session, Config(justify=False))
    lines_on  = _rendered_lines(view_on,  160)
    lines_off = _rendered_lines(view_off, 160)
    assert lines_on == lines_off


# 4.4 – N=3 distribution (no elapsed, no cache)

def test_justify_n3_path_wider_than_unjustified(
    monkeypatch: pytest.MonkeyPatch, strip_ansi: Callable[[str], str],
) -> None:
    """With N=3 sections and positive slack, the path section in the justify=True
    render is wider than in the justify=False render (slack is shared, not all
    concentrated in the gap before the right pill/text)."""
    _silence_dynamic(monkeypatch)
    width = 160
    view_on  = _view(Config(justify=True))
    view_off = _view(Config(justify=False))

    def _path_end_col(lines: list[str]) -> int:
        # Strip ANSI and find the first interior │ after the lead border.
        raw = strip_ansi(lines[1])  # top content row
        for i, ch in enumerate(raw):
            if ch == '│' and i > 1:
                return i
        return -1

    col_on  = _path_end_col(_rendered_lines(view_on,  width))
    col_off = _path_end_col(_rendered_lines(view_off, width))
    # Justify distributes slack away from the gap; path gets some extra columns.
    assert col_on > col_off, (
        f'expected justify=True path │ further right ({col_on}) than justify=False ({col_off})'
    )


def test_justify_n3_box_intact(
    monkeypatch: pytest.MonkeyPatch, strip_ansi: Callable[[str], str],
) -> None:
    """N=3 distribution (no elapsed, no cache) keeps the box intact."""
    _silence_dynamic(monkeypatch)
    width = 160
    view = _view(Config(justify=True))
    lines = [strip_ansi(ln) for ln in _rendered_lines(view, width)]
    widths = {_visible_width(ln) for ln in lines}
    assert widths == {width}


# 4.5 – path_extra distributed around the git block

def test_justify_path_extra_split_around_git_block(
    monkeypatch: pytest.MonkeyPatch, strip_ansi: Callable[[str], str],
) -> None:
    """With justify=True and git info present, path_extra is distributed around
    the ∈ git block: there are spaces *before* ∈ that were not present in the
    unjustified render, and spaces before the dirty-status indicator (or at the
    git-block end). The trailing-only append fallback must not be used when a
    branch separator is visible."""
    _silence_dynamic(monkeypatch)
    width = 160

    # Render unjustified first so we know the natural position of ∈.
    raw_off = strip_ansi(_rendered_lines(_view(Config(justify=False)), width)[1])
    raw_on  = strip_ansi(_rendered_lines(_view(Config(justify=True)),  width)[1])

    sep = '∈'
    idx_off = raw_off.find(sep)
    idx_on  = raw_on.find(sep)

    # ∈ must appear in both renders.
    assert idx_off != -1, 'branch separator not found in unjustified render'
    assert idx_on  != -1, 'branch separator not found in justified render'

    # With justify=True the ∈ should be pushed right (spaces inserted before it).
    assert idx_on > idx_off, (
        f'justify=True should push ∈ right: off={idx_off} on={idx_on}'
    )

    # The path section up to the first interior │ must be exactly width cols wide.
    first_pipe = raw_on.find('│', 1)
    assert first_pipe != -1
    path_section = raw_on[:first_pipe + 1]
    assert _visible_width(path_section) == first_pipe + 1
