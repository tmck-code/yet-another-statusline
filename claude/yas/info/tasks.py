from __future__ import annotations
import json
import time
from datetime import datetime
from pathlib import Path

from yas.constants import _sanitize


def _parse_iso_to_epoch(ts: str) -> float:
    try:
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


class Task:
    __slots__ = ('id', 'subject', 'active_form', 'status', 'started_at', 'completed_at')

    def __init__(
        self,
        id:           int,
        subject:      str,
        active_form:  str,
        status:       str,  # 'pending' | 'in_progress' | 'completed'
        started_at:   float | None = None,    # epoch secs of latest → in_progress (D1)
        completed_at: float | None = None,    # epoch secs of latest → completed (D1)
    ) -> None:
        self.id           = id
        self.subject      = subject
        self.active_form  = active_form
        self.status       = status
        self.started_at   = started_at
        self.completed_at = completed_at

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Task):
            return NotImplemented
        return (self.id, self.subject, self.active_form, self.status, self.started_at, self.completed_at) == \
               (other.id, other.subject, other.active_form, other.status, other.started_at, other.completed_at)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (f'Task(id={self.id}, subject={self.subject!r}, active_form={self.active_form!r}, '
                f'status={self.status!r}, started_at={self.started_at}, completed_at={self.completed_at})')


class TaskList:
    __slots__ = ('tasks', 'last_event_ts')

    FRESHNESS_CAP = 120.0  # 2 min — see docs/adr/0004
    GRACE_SECONDS = 20.0   # matches RunningSubagents.STALE_SECONDS

    def __init__(self, tasks: list[Task] | None = None, last_event_ts: float = 0.0) -> None:
        self.tasks         = tasks if tasks is not None else []
        self.last_event_ts = last_event_ts

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TaskList):
            return NotImplemented
        return self.tasks == other.tasks and self.last_event_ts == other.last_event_ts

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'TaskList(tasks={self.tasks!r}, last_event_ts={self.last_event_ts})'

    @classmethod
    def from_session(cls, transcript_path: str) -> TaskList:
        if not transcript_path:
            return cls()
        path = Path(transcript_path)
        if not path.is_file():
            return cls()
        by_id: dict[int, Task] = {}
        next_id = 1
        last_ts = 0.0
        try:
            with path.open('r', errors='ignore') as fh:
                for ln in fh:
                    if '"TaskCreate"' not in ln and '"TaskUpdate"' not in ln:
                        continue
                    try:
                        d = json.loads(ln)
                    except ValueError:
                        continue
                    ts = _parse_iso_to_epoch(d.get('timestamp', ''))
                    content = d.get('message', {}).get('content', [])
                    if not isinstance(content, list):
                        continue
                    for c in content:
                        if not isinstance(c, dict) or c.get('type') != 'tool_use':
                            continue
                        name = c.get('name', '')
                        inp  = c.get('input') or {}
                        if name == 'TaskCreate':
                            # D2: a TaskCreate folded while all known tasks are
                            # completed (and at least one exists) opens a new
                            # generation — discard prior tasks, restart ids at 1.
                            if by_id and all(t.status == 'completed' for t in by_id.values()):
                                by_id = {}
                                next_id = 1
                            subj = _sanitize(inp.get('subject', '') or '')
                            af   = _sanitize(inp.get('activeForm', '') or '') or subj
                            by_id[next_id] = Task(id=next_id, subject=subj, active_form=af, status='pending')
                            next_id += 1
                            if ts > last_ts: last_ts = ts
                        elif name == 'TaskUpdate':
                            try:
                                tid = int(inp.get('taskId', '0'))
                            except (TypeError, ValueError):
                                continue
                            t = by_id.get(tid)
                            if not t:
                                continue
                            new_status = inp.get('status')
                            if new_status in ('pending', 'in_progress', 'completed'):
                                # D1: capture per-task timestamps on transitions.
                                if new_status == 'in_progress':
                                    t.started_at = ts
                                    t.completed_at = None
                                elif new_status == 'completed':
                                    t.completed_at = ts
                                t.status = new_status
                            if 'activeForm' in inp and inp['activeForm']:
                                t.active_form = _sanitize(inp['activeForm'])
                            if 'subject' in inp and inp['subject']:
                                t.subject = _sanitize(inp['subject'])
                            if ts > last_ts: last_ts = ts
        except OSError:
            return cls()
        tasks = [by_id[k] for k in sorted(by_id.keys())]
        return cls(tasks=tasks, last_event_ts=last_ts)

    @property
    def total(self) -> int:
        return len(self.tasks)

    @property
    def completed(self) -> int:
        return sum(1 for t in self.tasks if t.status == 'completed')

    @property
    def active(self) -> Task | None:
        for t in reversed(self.tasks):
            if t.status == 'in_progress':
                return t
        return None

    @property
    def next_pending(self) -> Task | None:
        for t in self.tasks:
            if t.status == 'pending':
                return t
        return None

    def is_visible(self, now: float | None = None) -> bool:
        if not self.tasks or self.last_event_ts <= 0:
            return False
        if now is None:
            now = time.time()
        # D5: pinned visible while any task is in_progress, regardless of cap —
        # a long-running step emits no event but its live timer proves freshness.
        if any(t.status == 'in_progress' for t in self.tasks):
            return True
        age = now - self.last_event_ts
        if age > self.FRESHNESS_CAP:
            return False
        if self.completed == self.total:
            return age <= self.GRACE_SECONDS
        return True
