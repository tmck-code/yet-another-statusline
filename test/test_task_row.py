"""Tests for Renderer.task_row and build_wide/build_medium integration."""
import json
import time
from pathlib import Path

import pytest

import yas.constants as constants
import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
import yas.info.tasks as tasks_mod
from yas.config import Config
from yas.info import SessionView
from yas.render.text import _visible_width
from yas.constants import GLYPH_TASKS, GLYPH_TASK_ACTIVE, GLYPH_TASK_DONE, GLYPH_TASK_PENDING
from yas.tokens import TickRecord, TokenLog
from helper import strip_ansi


_r = renderer_mod.Renderer()

SESSION = (Path(__file__).parent.parent / 'ops'
           / 'session-info-example.json')


def _row(*args, **kwargs) -> str:
    """Join task_row's list[str] return for single-line A/B-group assertions."""
    return '\n'.join(_r.task_row(*args, **kwargs))


def _make_tasks(
    tasks: list[tuple[str, str, str]] | None = None,
    last_event_ts: float | None = None,
    timestamps: list[tuple[float | None, float | None]] | None = None,
) -> tasks_mod.TaskList:
    """Build a TaskList directly (never via from_session).

    `tasks` is a list of (subject, active_form, status). `timestamps`, if
    given, is a parallel list of (started_at, completed_at) per task.
    """
    if tasks is None:
        tasks = [('first', 'Doing first', 'in_progress')]
    objs = []
    for i, (subj, af, status) in enumerate(tasks):
        started, completed = (timestamps[i] if timestamps else (None, None))
        objs.append(tasks_mod.Task(
            id=i + 1, subject=subj, active_form=af, status=status,
            started_at=started, completed_at=completed,
        ))
    if last_event_ts is None:
        last_event_ts = time.time() - 5
    return tasks_mod.TaskList(tasks=objs, last_event_ts=last_event_ts)


# A. task_row full-list formatting (wide/medium) — multi-line list output

def test_task_row_returns_list() -> None:
    out = _r.task_row(_make_tasks(), 100)
    assert isinstance(out, list)
    assert all(isinstance(line, str) for line in out)


def test_task_row_header_has_glyph_and_count() -> None:
    out = _r.task_row(_make_tasks([
        ('a', 'a', 'completed'),
        ('b', 'b', 'in_progress'),
        ('c', 'c', 'pending'),
    ]), 100)
    header = strip_ansi(out[0])
    assert GLYPH_TASKS in header
    assert '1/3' in header


def test_task_row_header_shows_total_elapsed() -> None:
    now = time.time()
    out = _r.task_row(_make_tasks(
        [('a', 'a', 'completed'), ('b', 'b', 'in_progress')],
        timestamps=[(now - 120, now - 90), (now - 90, None)],
    ), 120)
    header = strip_ansi(out[0])
    # Earliest start (120s ago) -> now while in_progress -> 2:00.
    assert '2:0' in header  # 2:0x, tolerant of the render-tick second


def test_task_row_header_elapsed_precedes_count_no_timer_glyph() -> None:
    now = time.time()
    out = _r.task_row(_make_tasks(
        [('a', 'a', 'completed'), ('b', 'b', 'in_progress')],
        timestamps=[(now - 120, now - 90), (now - 90, None)],
    ), 120)
    header = strip_ansi(out[0])
    # Order: Total Elapsed first (leading column), then the done/total count.
    assert header.index('2:0') < header.index('1/2')
    assert not hasattr(constants, 'GLYPH_TASK_TIMER')


def test_task_row_total_elapsed_absent_when_never_started() -> None:
    out = _r.task_row(_make_tasks([
        ('a', 'a', 'pending'),
        ('b', 'b', 'pending'),
    ]), 120)
    header = strip_ansi(out[0])
    assert GLYPH_TASKS in header
    assert ':' not in header  # no timer at all


def test_task_row_item_state_glyphs() -> None:
    out = _r.task_row(_make_tasks([
        ('done one', 'doing one', 'completed'),
        ('active two', 'doing two', 'in_progress'),
        ('pend three', 'doing three', 'pending'),
    ]), 120)
    body = '\n'.join(strip_ansi(line) for line in out[1:])
    assert GLYPH_TASK_DONE in body
    assert GLYPH_TASK_ACTIVE in body
    assert GLYPH_TASK_PENDING in body


def test_task_row_completed_shows_frozen_duration() -> None:
    now = time.time()
    out = _r.task_row(_make_tasks(
        [('done', 'doing', 'completed')],
        timestamps=[(now - 100, now - 5)],  # 95s frozen
    ), 120)
    item = strip_ansi(out[1])
    assert '1:35' in item


def test_task_row_in_progress_shows_live_duration() -> None:
    now = time.time()
    out = _r.task_row(_make_tasks(
        [('active', 'doing', 'in_progress')],
        timestamps=[(now - 65, None)],  # ~1:05 live
    ), 120)
    item = strip_ansi(out[1])
    assert '1:0' in item


def test_task_row_pending_shows_no_timer() -> None:
    out = _r.task_row(_make_tasks([
        ('pend', 'doing', 'pending'),
    ]), 120)
    item = strip_ansi(out[1])
    assert ':' not in item  # no m:ss timer on the pending row


def test_task_row_timers_align_in_fixed_leading_column() -> None:
    now = time.time()
    out = _r.task_row(_make_tasks(
        [
            ('short', 'doing short', 'completed'),       # 0:05
            ('longer one', 'doing longer', 'completed'),  # 12:34
            ('active', 'doing active', 'in_progress'),    # live
        ],
        timestamps=[
            (now - 5, now),
            (now - 754, now),
            (now - 30, None),
        ],
    ), 120)
    item_lines = out[1:]
    # Timers occupy a fixed leading column, so every item row shares one width.
    widths = {_visible_width(strip_ansi(line)) for line in item_lines}
    assert len(widths) == 1
    # Each timer renders before its subject text on the row.
    for line, subj in zip(item_lines, ('short', 'longer one', 'doing active')):
        s = strip_ansi(line)
        if ':' in s:
            assert s.index(':') < s.index(subj)


def test_task_row_per_task_timers_right_align_under_total_elapsed() -> None:
    now = time.time()
    out = _r.task_row(_make_tasks(
        [('done', 'doing', 'completed'), ('active', 'doing active', 'in_progress')],
        # total elapsed ~11:40 (5 wide); the completed task is 1:35 (4 wide).
        timestamps=[(now - 700, now - 605), (now - 605, None)],
    ), 120)
    header = strip_ansi(out[0])
    item   = strip_ansi(out[1])
    elapsed_tok = header.split()[0]   # leading Total Elapsed, e.g. '11:40'
    assert len(elapsed_tok) == 5
    # The narrower task timer gains a leading pad so its right edge lines up
    # with the Total Elapsed above it.
    assert item.startswith(' 1:35')
    assert item.index('1:35') + len('1:35') == len(elapsed_tok)


def test_task_row_long_subject_truncates_after_leading_timer() -> None:
    now = time.time()
    out = _r.task_row(_make_tasks(
        [('A', 'z' * 200, 'in_progress')],
        timestamps=[(now - 30, None)],
    ), 80)
    item = strip_ansi(out[1])
    assert '…' in item


def test_task_row_no_collapse_lines_and_numbered_window() -> None:
    # >4 tasks: the window clips to <= 4 items with NO `+N done` / `+N more`
    # collapse lines, and each item carries its 1-indexed task number.
    now = time.time()
    specs = []
    ts = []
    for i in range(10):
        if i < 4:
            specs.append((f's{i}', f'doing {i}', 'completed'))
            ts.append((now - 100, now - 50))
        elif i == 4:
            specs.append((f's{i}', f'doing {i}', 'in_progress'))
            ts.append((now - 50, None))
        else:
            specs.append((f's{i}', f'doing {i}', 'pending'))
            ts.append((None, None))
    out = _r.task_row(_make_tasks(specs, timestamps=ts), 120)
    body = '\n'.join(strip_ansi(line) for line in out)
    assert 'done' not in body
    assert 'more' not in body
    # At most 4 item rows (excluding the header), active one anchored.
    assert len(out) - 1 <= 4
    # The active task is #5 (1-indexed) and renders its number.
    assert '5. doing 4' in body


@pytest.mark.parametrize('content_width', [40, 76, 96, 156])
def test_task_row_fits_supplied_content_width(content_width: int) -> None:
    # The builder supplies the inner content width directly (D4); every line
    # the renderer emits must fit within it, measured by visible width.
    now = time.time()
    out = _r.task_row(_make_tasks(
        [('A', 'x' * 200, 'in_progress'), ('B', 'y' * 200, 'pending')],
        timestamps=[(now - 30, None), (None, None)],
    ), content_width)
    for line in out:
        assert _visible_width(line) <= content_width


def test_task_row_honours_narrow_left_column_width() -> None:
    # A side-by-side left column is much narrower than the terminal; the
    # checklist must render its full structure into the supplied width and
    # truncate subjects to fit (no overflow past content_width).
    now = time.time()
    left_w = 30
    out = _r.task_row(_make_tasks(
        [
            ('done a', 'doing a', 'completed'),
            ('b', 'a very long active form that cannot possibly fit', 'in_progress'),
            ('c', 'doing c', 'pending'),
        ],
        timestamps=[(now - 100, now - 40), (now - 40, None), (None, None)],
    ), left_w)
    for line in out:
        assert _visible_width(line) <= left_w
    body = '\n'.join(strip_ansi(line) for line in out[1:])
    assert '…' in body  # the long subject truncated to fit the narrow column


def test_task_row_narrow_timers_still_right_align() -> None:
    # Even at a narrow supplied width the per-task timers share one leading
    # column so their right edges line up; all item rows share one width.
    now = time.time()
    out = _r.task_row(_make_tasks(
        [
            ('short', 'doing short', 'completed'),       # 0:05
            ('longer', 'doing longer', 'completed'),     # 12:34
            ('active', 'doing active', 'in_progress'),   # live
        ],
        timestamps=[(now - 5, now), (now - 754, now), (now - 30, None)],
    ), 34)
    item_lines = out[1:]
    widths = {_visible_width(strip_ansi(line)) for line in item_lines}
    assert len(widths) == 1
    # The narrower timer is left-padded so its right edge aligns with the wider
    # one (a fixed leading column), even at this narrow supplied width.
    timed = [strip_ansi(line) for line in item_lines if ':' in strip_ansi(line)]
    ends = {s.index(s.split()[0]) + len(s.split()[0]) for s in timed}
    assert len(ends) == 1


# B. task_row compact form (narrow)

def test_task_row_compact_returns_single_line() -> None:
    out = _r.task_row(_make_tasks([
        ('a', 'a', 'completed'),
        ('b', 'b', 'in_progress'),
    ]), 60, compact=True)
    assert len(out) == 1


def test_task_row_compact_has_count() -> None:
    out = _row(_make_tasks([
        ('a', 'a', 'completed'),
        ('b', 'b', 'in_progress'),
    ]), 100, compact=True)
    assert '1/2' in strip_ansi(out)


def test_task_row_compact_shows_active_timer() -> None:
    now = time.time()
    out = _r.task_row(_make_tasks(
        [('a', 'a', 'in_progress')],
        timestamps=[(now - 30, None)],
    ), 60, compact=True)
    line = strip_ansi(out[0])
    assert '0:3' in line  # ~0:30 live timer


def test_task_row_compact_omits_timer_when_nothing_active() -> None:
    out = _r.task_row(_make_tasks([
        ('a', 'a', 'completed'),
        ('b', 'b', 'pending'),
    ]), 60, compact=True)
    line = strip_ansi(out[0])
    assert ':' not in line  # no live timer


def test_task_row_compact_drops_active_form() -> None:
    out = _row(_make_tasks([('A', 'Doing distinctive thing', 'in_progress')]), 100, compact=True)
    assert 'Doing distinctive thing' not in strip_ansi(out)


def test_task_row_compact_right_anchors_timer() -> None:
    # The narrow header right-anchors the active-task timer to the content edge:
    # the row fills exactly to the content width and the last non-space content
    # is the live timer, with no trailing dead space before the (caller-added)
    # closing border.
    now = time.time()
    width = 78
    out = _r.task_row(_make_tasks(
        [('a', 'a', 'in_progress')],
        timestamps=[(now - 30, None)],
    ), width, compact=True)
    line = strip_ansi(out[0])
    assert _visible_width(line) == width
    # Last non-space content is the timer, flush to the content edge.
    assert line.rstrip().endswith('0:30')
    assert line.endswith('0:30')  # no trailing gap before the border


def test_task_row_compact_timer_truncates_left_no_overflow() -> None:
    # When the content is too narrow to hold both the left cluster and the
    # right-anchored timer, the left cluster ellipsizes and the row still fits
    # exactly — never overflows the content width.
    now = time.time()
    width = 12
    out = _r.task_row(_make_tasks(
        [('a', 'a', 'in_progress')],
        timestamps=[(now - 30, None)],
    ), width, compact=True)
    line = strip_ansi(out[0])
    assert _visible_width(line) == width
    assert line.endswith('0:30')


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
    # No in_progress task, so D5 pinned-visibility does not apply and the
    # freshness cap hides the stale list.
    tasks = _make_tasks(
        [('A', 'doing a', 'completed'), ('B', 'doing b', 'completed')],
        last_event_ts=time.time() - tasks_mod.TaskList.FRESHNESS_CAP - 10,
    )
    out = _render(monkeypatch, layout.build_wide, tasks, 120)
    assert GLYPH_TASKS not in strip_ansi(out)


def test_build_medium_visible_tasks_show_full_list(monkeypatch: pytest.MonkeyPatch) -> None:
    # D7: medium now renders the full header + Active Window (not count-only).
    tasks = _make_tasks([
        ('A', 'Distinctive active text', 'in_progress'),
        ('B', 'B', 'pending'),
    ])
    out = _render(monkeypatch, layout.build_medium, tasks, 90)
    stripped = strip_ansi(out)
    assert GLYPH_TASKS in stripped
    assert '0/2' in stripped
    assert 'Distinctive active text' in stripped


def test_build_medium_no_tasks_no_glyph(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _render(monkeypatch, layout.build_medium, tasks_mod.TaskList(), 90)
    assert GLYPH_TASKS not in strip_ansi(out)


def test_build_narrow_shows_compact_line(monkeypatch: pytest.MonkeyPatch) -> None:
    # D7: narrow now renders a single compact line (glyph + done/total +
    # the active live timer), with no per-item subject text.
    tasks = _make_tasks([('A', 'Distinctive active text', 'in_progress')])
    out = _render(monkeypatch, layout.build_narrow, tasks, 60)
    stripped = strip_ansi(out)
    assert GLYPH_TASKS in stripped
    assert '0/1' in stripped
    assert 'Distinctive active text' not in stripped


def test_build_narrow_no_tasks_no_glyph(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _render(monkeypatch, layout.build_narrow, tasks_mod.TaskList(), 60)
    assert GLYPH_TASKS not in strip_ansi(out)
