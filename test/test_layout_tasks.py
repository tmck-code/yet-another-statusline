import json
from pathlib import Path

import pytest

import statusline_command as sl
from helper import strip_ansi

_r = sl.Renderer()
SESSION = (Path(__file__).parent.parent / 'claude' / 'statusline'
           / 'session-info-example.json')

# Stub task lines emitted by task_row; chosen to be ANSI-free and unlikely to
# collide with any other content row prefix in the layout.
STUB_LINES = ['TASKLINE_HDR', 'TASKLINE_ITEM_1', 'TASKLINE_ITEM_2', 'TASKLINE_COLLAPSE']


def _session() -> sl.SessionInfo:
    return sl.SessionInfo.from_dict(json.loads(SESSION.read_text()))


def _no_subagents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sl.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir: sl.RunningSubagents(subagents=[])),
    )


def _stub_tasks(monkeypatch: pytest.MonkeyPatch, *, visible: bool, lines: list[str]) -> None:
    """Stub TaskList.from_session → a list, is_visible → `visible`, and
    task_row → the fixed `lines` so the builder wiring is exercised in
    isolation from the renderer / parser units."""
    monkeypatch.setattr(
        sl.TaskList, 'from_session',
        classmethod(lambda cls, path: sl.TaskList()),
    )
    monkeypatch.setattr(sl.TaskList, 'is_visible', lambda self, now=None: visible)
    monkeypatch.setattr(sl.Renderer, 'task_row', lambda self, tasks, width, *, compact=False: list(lines))


def _task_rows(spec: sl.LayoutSpec) -> list[sl.RowSpec]:
    return [
        row for row in spec.rows
        if row.kind == 'content' and strip_ansi(row.content) in STUB_LINES
    ]


# --- build_wide -------------------------------------------------------------

def test_build_wide_visible_emits_one_content_row_per_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    _stub_tasks(monkeypatch, visible=True, lines=STUB_LINES)
    spec = sl.build_wide(_session(), 140, _r)
    rows = _task_rows(spec)
    assert [strip_ansi(r.content) for r in rows] == STUB_LINES


def test_build_wide_not_visible_emits_no_task_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    _stub_tasks(monkeypatch, visible=False, lines=STUB_LINES)
    spec = sl.build_wide(_session(), 140, _r)
    assert _task_rows(spec) == []


# --- build_medium -----------------------------------------------------------

def test_build_medium_visible_emits_full_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    _stub_tasks(monkeypatch, visible=True, lines=STUB_LINES)
    spec = sl.build_medium(_session(), 120, _r)
    rows = _task_rows(spec)
    assert [strip_ansi(r.content) for r in rows] == STUB_LINES


def test_build_medium_calls_task_row_non_compact(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    seen: list[bool] = []

    def _spy(self: sl.Renderer, tasks: sl.TaskList, width: int, *, compact: bool = False) -> list[str]:
        seen.append(compact)
        return list(STUB_LINES)

    monkeypatch.setattr(
        sl.TaskList, 'from_session', classmethod(lambda cls, path: sl.TaskList()),
    )
    monkeypatch.setattr(sl.TaskList, 'is_visible', lambda self, now=None: True)
    monkeypatch.setattr(sl.Renderer, 'task_row', _spy)
    sl.build_medium(_session(), 120, _r)
    assert seen == [False]  # D7: medium shows the FULL list, not compact


def test_build_medium_not_visible_emits_no_task_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    _stub_tasks(monkeypatch, visible=False, lines=STUB_LINES)
    spec = sl.build_medium(_session(), 120, _r)
    assert _task_rows(spec) == []


# --- build_narrow -----------------------------------------------------------

def test_build_narrow_visible_emits_single_compact_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    # compact path: task_row returns exactly one line
    _stub_tasks(monkeypatch, visible=True, lines=['TASKLINE_HDR'])
    spec = sl.build_narrow(_session(), 80, _r)
    rows = _task_rows(spec)
    assert [strip_ansi(r.content) for r in rows] == ['TASKLINE_HDR']


def test_build_narrow_calls_task_row_compact(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    seen: list[bool] = []

    def _spy(self: sl.Renderer, tasks: sl.TaskList, width: int, *, compact: bool = False) -> list[str]:
        seen.append(compact)
        return ['TASKLINE_HDR']

    monkeypatch.setattr(
        sl.TaskList, 'from_session', classmethod(lambda cls, path: sl.TaskList()),
    )
    monkeypatch.setattr(sl.TaskList, 'is_visible', lambda self, now=None: True)
    monkeypatch.setattr(sl.Renderer, 'task_row', _spy)
    sl.build_narrow(_session(), 80, _r)
    assert seen == [True]  # D7: narrow shows the compact line


def test_build_narrow_not_visible_emits_no_task_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_subagents(monkeypatch)
    _stub_tasks(monkeypatch, visible=False, lines=['TASKLINE_HDR'])
    spec = sl.build_narrow(_session(), 80, _r)
    assert _task_rows(spec) == []
