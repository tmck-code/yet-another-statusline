"""Tests for the pure view helpers in tasks_view.py (D3/D4/D6).

These cover duration formatting, the generation Total Elapsed span, and the
active-anchored window selection. The helpers are bound onto the
`statusline_command` module by Foundation, mirroring `themes.py`.
"""
import statusline_command as sl

fmt_duration = sl.fmt_duration
total_elapsed = sl.total_elapsed
select_window = sl.select_window
WindowSlice = sl.WindowSlice


def _task(
    tid: int,
    status: str,
    *,
    started_at: float | None = None,
    completed_at: float | None = None,
) -> 'sl.Task':
    return sl.Task(
        id          = tid,
        subject     = f'task {tid}',
        active_form = f'doing task {tid}',
        status      = status,
        started_at  = started_at,
        completed_at= completed_at,
    )


# ---- §4.1 fmt_duration -----------------------------------------------------

def test_fmt_duration_zero() -> None:
    assert fmt_duration(0) == '0:00'


def test_fmt_duration_seconds_zero_padded() -> None:
    assert fmt_duration(7) == '0:07'


def test_fmt_duration_minutes_not_padded() -> None:
    assert fmt_duration(12 * 60 + 4) == '12:04'


def test_fmt_duration_truncates_fractional_seconds() -> None:
    assert fmt_duration(7.9) == '0:07'


def test_fmt_duration_rolls_over_at_one_hour() -> None:
    assert fmt_duration(3600) == '1:00:00'


def test_fmt_duration_hours_minutes_seconds() -> None:
    assert fmt_duration(3661) == '1:01:01'


def test_fmt_duration_just_below_rollover() -> None:
    assert fmt_duration(3599) == '59:59'


# ---- §4.3 total_elapsed ----------------------------------------------------

def test_total_elapsed_none_when_nothing_started() -> None:
    tl = sl.TaskList(tasks=[_task(1, 'pending'), _task(2, 'pending')])
    assert total_elapsed(tl, now=1000.0) is None


def test_total_elapsed_live_while_in_progress() -> None:
    tl = sl.TaskList(tasks=[
        _task(1, 'completed', started_at=100.0, completed_at=150.0),
        _task(2, 'in_progress', started_at=200.0),
    ])
    # earliest start is 100, in_progress -> now - earliest
    assert total_elapsed(tl, now=300.0) == 200.0


def test_total_elapsed_frozen_when_all_complete() -> None:
    tl = sl.TaskList(tasks=[
        _task(1, 'completed', started_at=100.0, completed_at=150.0),
        _task(2, 'completed', started_at=160.0, completed_at=240.0),
    ])
    # latest completed (240) - earliest start (100); independent of now
    assert total_elapsed(tl, now=9999.0) == 140.0


def test_total_elapsed_ignores_never_started_tasks() -> None:
    tl = sl.TaskList(tasks=[
        _task(1, 'pending'),
        _task(2, 'completed', started_at=500.0, completed_at=560.0),
    ])
    assert total_elapsed(tl, now=9999.0) == 60.0


def test_total_elapsed_fallback_when_started_but_no_completed() -> None:
    # started, nothing in_progress, nothing completed -> graceful now - earliest
    tl = sl.TaskList(tasks=[_task(1, 'pending', started_at=100.0)])
    assert total_elapsed(tl, now=250.0) == 150.0


# ---- §4.5 select_window ----------------------------------------------------

def _assert_budget(ws: 'WindowSlice', budget: int = 4) -> None:
    # No collapse lines any more — the window is a pure <= budget item slice.
    assert len(ws.items) <= budget, f'{len(ws.items)} items > budget {budget}'


def test_select_window_short_plan_returns_all() -> None:
    tasks = [_task(1, 'completed'), _task(2, 'in_progress'), _task(3, 'pending')]
    tl = sl.TaskList(tasks=tasks)
    ws = select_window(tl)
    assert ws.items == tasks
    assert ws.done_hidden == 0
    assert ws.more_hidden == 0
    _assert_budget(ws)


def test_select_window_exactly_budget_returns_all() -> None:
    tasks = [_task(i, 'pending') for i in range(1, 5)]
    tasks[2].status = 'in_progress'
    tl = sl.TaskList(tasks=tasks)
    ws = select_window(tl)
    assert ws.items == tasks
    assert ws.done_hidden == 0
    assert ws.more_hidden == 0
    _assert_budget(ws)


def test_select_window_long_plan_keeps_active_and_budget() -> None:
    # 20 tasks, active in the middle, completed before, pending after.
    tasks: list[sl.Task] = []
    for i in range(1, 21):
        if i < 10:
            tasks.append(_task(i, 'completed'))
        elif i == 10:
            tasks.append(_task(i, 'in_progress'))
        else:
            tasks.append(_task(i, 'pending'))
    tl = sl.TaskList(tasks=tasks)
    ws = select_window(tl)
    active = tl.active
    assert active in ws.items, 'in_progress task must be in the window'
    _assert_budget(ws)
    # hidden counts are exact: total not shown split above/below
    shown_ids = {t.id for t in ws.items}
    above = sum(1 for t in tasks if t.id not in shown_ids and t.id < active.id)
    below = sum(1 for t in tasks if t.id not in shown_ids and t.id > active.id)
    assert ws.done_hidden == above
    assert ws.more_hidden == below


def test_select_window_active_at_start_long() -> None:
    tasks = [_task(1, 'in_progress')] + [_task(i, 'pending') for i in range(2, 21)]
    tl = sl.TaskList(tasks=tasks)
    ws = select_window(tl)
    assert tl.active in ws.items
    assert ws.done_hidden == 0  # nothing completed above
    _assert_budget(ws)


def test_select_window_active_at_end_long() -> None:
    tasks = [_task(i, 'completed') for i in range(1, 20)] + [_task(20, 'in_progress')]
    tl = sl.TaskList(tasks=tasks)
    ws = select_window(tl)
    assert tl.active in ws.items
    assert ws.more_hidden == 0  # nothing pending below
    _assert_budget(ws)


def test_select_window_no_active_shows_first_pendings() -> None:
    tasks = [_task(i, 'pending') for i in range(1, 21)]
    tl = sl.TaskList(tasks=tasks)
    ws = select_window(tl)
    assert ws.items[0].id == 1, 'no active -> window from the start'
    assert ws.done_hidden == 0
    _assert_budget(ws)
    shown_ids = {t.id for t in ws.items}
    assert ws.more_hidden == sum(1 for t in tasks if t.id not in shown_ids)


def test_select_window_all_complete_shows_last_completeds() -> None:
    tasks = [_task(i, 'completed') for i in range(1, 21)]
    tl = sl.TaskList(tasks=tasks)
    ws = select_window(tl)
    assert ws.items[-1].id == 20, 'all complete -> window the last completeds'
    assert ws.more_hidden == 0
    _assert_budget(ws)
    shown_ids = {t.id for t in ws.items}
    assert ws.done_hidden == sum(1 for t in tasks if t.id not in shown_ids)


def test_select_window_single_task() -> None:
    tl = sl.TaskList(tasks=[_task(1, 'in_progress')])
    ws = select_window(tl)
    assert len(ws.items) == 1
    assert ws.done_hidden == 0 and ws.more_hidden == 0
    _assert_budget(ws)


def test_select_window_seven_tasks_clips_to_budget() -> None:
    # 7 tasks > budget 4: window clips, exact above/below counts reported.
    tasks = [_task(i, 'completed') for i in range(1, 4)]
    tasks += [_task(4, 'in_progress')]
    tasks += [_task(i, 'pending') for i in range(5, 8)]
    tl = sl.TaskList(tasks=tasks)
    ws = select_window(tl)
    assert tl.active in ws.items
    _assert_budget(ws)
    shown_ids = {t.id for t in ws.items}
    active_id = tl.active.id
    assert ws.done_hidden == sum(1 for t in tasks if t.id not in shown_ids and t.id < active_id)
    assert ws.more_hidden == sum(1 for t in tasks if t.id not in shown_ids and t.id > active_id)


def test_select_window_budget_holds_across_active_positions() -> None:
    n = 12
    for active_pos in range(n):
        tasks = []
        for i in range(n):
            if i < active_pos:
                tasks.append(_task(i + 1, 'completed'))
            elif i == active_pos:
                tasks.append(_task(i + 1, 'in_progress'))
            else:
                tasks.append(_task(i + 1, 'pending'))
        tl = sl.TaskList(tasks=tasks)
        ws = select_window(tl)
        assert tl.active in ws.items, f'active_pos={active_pos}'
        _assert_budget(ws)
        shown_ids = {t.id for t in ws.items}
        active_id = tl.active.id
        above = sum(1 for t in tasks if t.id not in shown_ids and t.id < active_id)
        below = sum(1 for t in tasks if t.id not in shown_ids and t.id > active_id)
        assert ws.done_hidden == above, f'active_pos={active_pos}'
        assert ws.more_hidden == below, f'active_pos={active_pos}'
