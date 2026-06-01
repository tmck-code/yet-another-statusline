import json
from pathlib import Path

import pytest

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
import yas.info.tasks as tasks_mod
import yas.info.subagents as subagents_mod
from yas.config import Config
from yas.info import SessionView
from yas.tokens import TickRecord, TokenLog
from helper import strip_ansi

_r = renderer_mod.Renderer()
SESSION = (Path(__file__).parent.parent / 'ops'
           / 'session-info-example.json')

# Stub task lines emitted by task_row; chosen to be ANSI-free and unlikely to
# collide with any other content row prefix in the layout.
STUB_LINES = ['TASKLINE_HDR', 'TASKLINE_ITEM_1', 'TASKLINE_ITEM_2', 'TASKLINE_COLLAPSE']


def _view() -> SessionView:
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    return SessionView(session, Config())


def _spec(builder, width: int) -> layout.LayoutSpec:
    """Run a builder, injecting the TickRecord that build_wide needs."""
    view = _view()
    if builder is layout.build_wide:
        return builder(view, TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0), width, _r)
    return builder(view, width, _r)


def _no_subagents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[])),
    )


def _stub_tasks(monkeypatch: pytest.MonkeyPatch, *, visible: bool, lines: list[str]) -> None:
    """Stub TaskList.from_session → a list, is_visible → `visible`, and
    task_row → the fixed `lines` so the builder wiring is exercised in
    isolation from the renderer / parser units."""
    monkeypatch.setattr(
        tasks_mod.TaskList, 'from_session',
        classmethod(lambda cls, path: tasks_mod.TaskList()),
    )
    monkeypatch.setattr(tasks_mod.TaskList, 'is_visible', lambda self, now=None: visible)
    monkeypatch.setattr(renderer_mod.Renderer, 'task_row', lambda self, tasks, width, *, compact=False: list(lines))


def _task_rows(spec: layout.LayoutSpec) -> list[layout.RowSpec]:
    return [
        row for row in spec.rows
        if row.kind == 'content' and strip_ansi(row.content) in STUB_LINES
    ]


# --- build_wide -------------------------------------------------------------

def test_build_wide_visible_emits_one_content_row_per_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    _stub_tasks(monkeypatch, visible=True, lines=STUB_LINES)
    spec = _spec(layout.build_wide, 140)
    rows = _task_rows(spec)
    assert [strip_ansi(r.content) for r in rows] == STUB_LINES


def test_build_wide_not_visible_emits_no_task_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    _stub_tasks(monkeypatch, visible=False, lines=STUB_LINES)
    spec = _spec(layout.build_wide, 140)
    assert _task_rows(spec) == []


# --- build_medium -----------------------------------------------------------

def test_build_medium_visible_emits_full_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    _stub_tasks(monkeypatch, visible=True, lines=STUB_LINES)
    spec = _spec(layout.build_medium, 120)
    rows = _task_rows(spec)
    assert [strip_ansi(r.content) for r in rows] == STUB_LINES


def test_build_medium_calls_task_row_non_compact(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    seen: list[bool] = []

    def _spy(self: renderer_mod.Renderer, tasks: tasks_mod.TaskList, width: int, *, compact: bool = False) -> list[str]:
        seen.append(compact)
        return list(STUB_LINES)

    monkeypatch.setattr(
        tasks_mod.TaskList, 'from_session', classmethod(lambda cls, path: tasks_mod.TaskList()),
    )
    monkeypatch.setattr(tasks_mod.TaskList, 'is_visible', lambda self, now=None: True)
    monkeypatch.setattr(renderer_mod.Renderer, 'task_row', _spy)
    _spec(layout.build_medium, 120)
    assert seen == [False]  # D7: medium shows the FULL list, not compact


def test_build_medium_not_visible_emits_no_task_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    _stub_tasks(monkeypatch, visible=False, lines=STUB_LINES)
    spec = _spec(layout.build_medium, 120)
    assert _task_rows(spec) == []


# --- build_narrow -----------------------------------------------------------

def test_build_narrow_visible_emits_single_compact_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    # compact path: task_row returns exactly one line
    _stub_tasks(monkeypatch, visible=True, lines=['TASKLINE_HDR'])
    spec = _spec(layout.build_narrow, 80)
    rows = _task_rows(spec)
    assert [strip_ansi(r.content) for r in rows] == ['TASKLINE_HDR']


def test_build_narrow_calls_task_row_compact(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    seen: list[bool] = []

    def _spy(self: renderer_mod.Renderer, tasks: tasks_mod.TaskList, width: int, *, compact: bool = False) -> list[str]:
        seen.append(compact)
        return ['TASKLINE_HDR']

    monkeypatch.setattr(
        tasks_mod.TaskList, 'from_session', classmethod(lambda cls, path: tasks_mod.TaskList()),
    )
    monkeypatch.setattr(tasks_mod.TaskList, 'is_visible', lambda self, now=None: True)
    monkeypatch.setattr(renderer_mod.Renderer, 'task_row', _spy)
    _spec(layout.build_narrow, 80)
    assert seen == [True]  # D7: narrow shows the compact line


def test_build_narrow_not_visible_emits_no_task_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    _stub_tasks(monkeypatch, visible=False, lines=['TASKLINE_HDR'])
    spec = _spec(layout.build_narrow, 80)
    assert _task_rows(spec) == []
