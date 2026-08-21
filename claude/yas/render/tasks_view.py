"""Pure view helpers for the task checklist (no ANSI, no I/O)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yas.info.tasks import Task, TaskList


class WindowSlice:
    """Active-anchored window of `Task`s to draw, plus counts clipped above/below."""

    __slots__ = ('items', 'done_hidden', 'more_hidden')

    def __init__(
        self,
        items:       'list[Task] | None' = None,
        done_hidden: int = 0,
        more_hidden: int = 0,
    ) -> None:
        self.items       = items if items is not None else []
        self.done_hidden = done_hidden
        self.more_hidden = more_hidden


def fmt_duration(secs: float) -> str:
    """Format as `m:ss`, rolling to `h:mm:ss` at >= 1 hour."""
    total = int(secs)
    if total < 0:
        total = 0
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{seconds:02d}'
    return f'{minutes}:{seconds:02d}'


def total_elapsed(tasks: TaskList, now: float) -> float | None:
    """Wall-clock span of the current generation: earliest start -> now (live) or -> latest completion (frozen)."""
    items = tasks.tasks
    starts = [t.started_at for t in items if t.started_at is not None]
    if not starts:
        return None
    earliest = min(starts)
    if any(t.status == 'in_progress' for t in items):
        return now - earliest
    completes = [t.completed_at for t in items if t.completed_at is not None]
    if not completes:
        return now - earliest  # started but nothing completed -> fall back
    return max(completes) - earliest


def select_window(tasks: TaskList, budget: int = 4) -> WindowSlice:
    """Active-anchored window of <= `budget` task rows; in_progress task, if any, sits one row from the top."""
    items = tasks.tasks
    n = len(items)

    if n <= budget:
        return WindowSlice(items=list(items), done_hidden=0, more_hidden=0)

    active = tasks.active
    if active is None:
        # anchor to the end when all complete, else to the start
        if all(t.status == 'completed' for t in items):
            start = n - budget
            return WindowSlice(items=list(items[start:]), done_hidden=start, more_hidden=0)
        return WindowSlice(items=list(items[:budget]), done_hidden=0, more_hidden=n - budget)

    # keep one row of context above active, rest to pendings that follow
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
