"""Pure view helpers for the task checklist (no ANSI, no I/O).

These isolate the testable maths behind `Renderer.task_row`: duration
formatting, the generation's Total Elapsed wall-clock span, and the
active-anchored window selection. `Renderer.task_row` composes ANSI/colour
around their results. See `task-checklist-timers` design D3/D4/D6/D9.

Loaded via `importlib` from `statusline_command.py`, mirroring `themes.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from statusline_command import Task, TaskList


@dataclass
class WindowSlice:
    """The slice of tasks to render plus the clipped-away counts.

    `items` is the active-anchored window of `Task`s to draw. `done_hidden`
    is the number of tasks clipped above the window and `more_hidden` the
    number clipped below. Both are informational only — the **Task Checklist**
    renders the windowed items (each carrying its own task number) with no
    `+N done` / `+N more` collapse lines. See `select_window`.
    """

    items: list[Task] = field(default_factory=list)
    done_hidden: int = 0
    more_hidden: int = 0


def fmt_duration(secs: float) -> str:
    """Format a duration as `m:ss`, rolling to `h:mm:ss` at >= 1 hour (D4).

    Minutes/hours are not zero-padded; seconds (and minutes once hours show)
    are. Fractional seconds floor to int: `0:00`, `0:07`, `12:04`, `1:01:01`.
    """
    total = int(secs)
    if total < 0:
        total = 0
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{seconds:02d}'
    return f'{minutes}:{seconds:02d}'


def total_elapsed(tasks: TaskList, now: float) -> float | None:
    """Wall-clock span of the current generation, or None if never started (D6).

    Earliest `started_at` -> `now` while any task is in_progress (live), else
    -> latest `completed_at` (frozen). None when nothing ever started.
    """
    items = tasks.tasks
    starts = [t.started_at for t in items if t.started_at is not None]
    if not starts:
        return None
    earliest = min(starts)
    if any(t.status == 'in_progress' for t in items):
        return now - earliest
    completes = [t.completed_at for t in items if t.completed_at is not None]
    if not completes:
        # Started but nothing in progress and nothing completed — fall back.
        return now - earliest
    return max(completes) - earliest


def select_window(tasks: TaskList, budget: int = 4) -> WindowSlice:
    """Active-anchored window of <= `budget` task rows (D3).

    Returns the slice of tasks to draw plus the clipped-away counts (above /
    below the window) for callers that want them — the renderer itself draws
    no collapse lines. The `in_progress` task (if any) is always in `items`,
    placed one row from the window top so a single completed task of context
    leads it and the remaining budget shows the following pendings. With no
    active task we window from the first pending; when all complete we window
    the last completeds.
    """
    items = tasks.tasks
    n = len(items)

    # Short plan: everything fits.
    if n <= budget:
        return WindowSlice(items=list(items), done_hidden=0, more_hidden=0)

    active = tasks.active
    if active is None:
        # No in_progress task. All-complete -> anchor to the end (last
        # completeds); otherwise anchor to the start (first pendings).
        if all(t.status == 'completed' for t in items):
            start = n - budget
            return WindowSlice(items=list(items[start:]), done_hidden=start, more_hidden=0)
        return WindowSlice(items=list(items[:budget]), done_hidden=0, more_hidden=n - budget)

    # Active present: keep one row of context above it, give the rest to the
    # pendings that follow, clamping to the list bounds at either end.
    a    = items.index(active)
    lead = 1 if a > 0 else 0
    start = a - lead
    end   = start + budget
    if end > n:
        end   = n
        start = max(0, end - budget)
    return WindowSlice(
        items       = list(items[start:end]),
        done_hidden = start,
        more_hidden = n - end,
    )
