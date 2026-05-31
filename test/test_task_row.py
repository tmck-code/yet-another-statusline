"""Tests for Renderer.task_row and build_wide/build_medium integration."""
import json
import time
from pathlib import Path

import pytest

import statusline.layout as layout
import statusline.renderer as renderer_mod
import statusline.session as session_mod
import statusline.tasks as tasks_mod
from statusline.config import Config
from statusline.info import SessionView
from statusline.text import _visible_width
from statusline.constants import GLYPH_TASKS
from statusline.tokens import TickRecord, TokenLog
from helper import strip_ansi


_r = renderer_mod.Renderer()

SESSION = (Path(__file__).parent.parent / 'claude' / 'statusline'
           / 'session-info-example.json')


def _make_tasks(
    tasks: list[tuple[str, str, str]] | None = None,
    last_event_ts: float | None = None,
) -> tasks_mod.TaskList:
    if tasks is None:
        tasks = [('first', 'Doing first', 'in_progress')]
    objs = [
        tasks_mod.Task(id=i + 1, subject=subj, active_form=af, status=status)
        for i, (subj, af, status) in enumerate(tasks)
    ]
    if last_event_ts is None:
        last_event_ts = time.time() - 5
    return tasks_mod.TaskList(tasks=objs, last_event_ts=last_event_ts)


# A. task_row formatting (wide)

def test_task_row_includes_glyph() -> None:
    out = _r.task_row(_make_tasks(), 100)
    assert GLYPH_TASKS in strip_ansi(out)


def test_task_row_shows_count() -> None:
    out = _r.task_row(_make_tasks([
        ('a', 'a', 'completed'),
        ('b', 'b', 'in_progress'),
        ('c', 'c', 'pending'),
    ]), 100)
    assert '1/3' in strip_ansi(out)


def test_task_row_shows_active_form() -> None:
    out = _r.task_row(_make_tasks([('First', 'Doing the first thing', 'in_progress')]), 100)
    assert 'Doing the first thing' in strip_ansi(out)


def test_task_row_all_done_drops_text() -> None:
    out = _r.task_row(_make_tasks([
        ('a', 'doing a', 'completed'),
        ('b', 'doing b', 'completed'),
    ]), 100)
    stripped = strip_ansi(out)
    assert '2/2' in stripped
    assert 'doing' not in stripped


def test_task_row_pending_only_shows_next_subject() -> None:
    out = _r.task_row(_make_tasks([
        ('First subject', 'doing first', 'pending'),
        ('Second subject', 'doing second', 'pending'),
    ]), 100)
    assert 'First subject' in strip_ansi(out)


@pytest.mark.parametrize('width', [80, 100, 160])
def test_task_row_fits_inner_width(width: int) -> None:
    out = _r.task_row(_make_tasks([('A', 'x' * 200, 'in_progress')]), width)
    assert _visible_width(out) <= width - 3


def test_task_row_long_active_form_elides() -> None:
    out = _r.task_row(_make_tasks([('A', 'x' * 200, 'in_progress')]), 80)
    assert '…' in strip_ansi(out)


# B. task_row compact form (medium)

def test_task_row_compact_has_count() -> None:
    out = _r.task_row(_make_tasks([
        ('a', 'a', 'completed'),
        ('b', 'b', 'in_progress'),
    ]), 100, compact=True)
    assert '1/2' in strip_ansi(out)


def test_task_row_compact_drops_active_form() -> None:
    out = _r.task_row(_make_tasks([('A', 'Doing distinctive thing', 'in_progress')]), 100, compact=True)
    assert 'Doing distinctive thing' not in strip_ansi(out)


# C. build_wide / build_medium integration

def _render(monkeypatch: pytest.MonkeyPatch, builder, tasks: tasks_mod.TaskList, width: int) -> str:
    monkeypatch.setattr(
        tasks_mod.TaskList, 'from_session',
        classmethod(lambda cls, transcript_path: tasks),
    )
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    view    = SessionView(session, Config())
    if builder is layout.build_wide:
        spec = builder(view, TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0), width, _r)
    else:
        spec = builder(view, width, _r)
    return '\n'.join(layout.render_layout(spec, _r))


def test_build_wide_no_tasks_no_glyph(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _render(monkeypatch, layout.build_wide, tasks_mod.TaskList(), 120)
    assert GLYPH_TASKS not in strip_ansi(out)


def test_build_wide_visible_tasks_show_row(monkeypatch: pytest.MonkeyPatch) -> None:
    tasks = _make_tasks([
        ('A', 'Doing A', 'in_progress'),
        ('B', 'B', 'pending'),
    ])
    out = _render(monkeypatch, layout.build_wide, tasks, 120)
    stripped = strip_ansi(out)
    assert GLYPH_TASKS in stripped
    assert '0/2' in stripped
    assert 'Doing A' in stripped


def test_build_wide_stale_tasks_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    tasks = _make_tasks(
        [('A', 'doing a', 'in_progress')],
        last_event_ts=time.time() - tasks_mod.TaskList.FRESHNESS_CAP - 10,
    )
    out = _render(monkeypatch, layout.build_wide, tasks, 120)
    assert GLYPH_TASKS not in strip_ansi(out)


def test_build_medium_visible_tasks_show_count_only(monkeypatch: pytest.MonkeyPatch) -> None:
    tasks = _make_tasks([
        ('A', 'Distinctive active text', 'in_progress'),
        ('B', 'B', 'pending'),
    ])
    out = _render(monkeypatch, layout.build_medium, tasks, 90)
    stripped = strip_ansi(out)
    assert GLYPH_TASKS in stripped
    assert '0/2' in stripped
    assert 'Distinctive active text' not in stripped


def test_build_medium_no_tasks_no_glyph(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _render(monkeypatch, layout.build_medium, tasks_mod.TaskList(), 90)
    assert GLYPH_TASKS not in strip_ansi(out)


def test_build_narrow_never_shows_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    tasks = _make_tasks([('A', 'Doing A', 'in_progress')])
    out = _render(monkeypatch, layout.build_narrow, tasks, 60)
    assert GLYPH_TASKS not in strip_ansi(out)
