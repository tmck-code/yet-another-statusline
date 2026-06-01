from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def _parse_iso_to_epoch(ts: str) -> float:
    try:
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


@dataclass
class Task:
    id: int
    subject: str
    active_form: str
    status: str  # 'pending' | 'in_progress' | 'completed'


@dataclass
class TaskList:
    tasks: list[Task] = field(default_factory=list)
    last_event_ts: float = 0.0

    FRESHNESS_CAP = 120.0  # 2 min — see docs/adr/0004
    GRACE_SECONDS = 20.0   # matches RunningSubagents.STALE_SECONDS

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
                            subj = inp.get('subject', '') or ''
                            af   = inp.get('activeForm', '') or subj
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
                                t.status = new_status
                            if 'activeForm' in inp and inp['activeForm']:
                                t.active_form = inp['activeForm']
                            if 'subject' in inp and inp['subject']:
                                t.subject = inp['subject']
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
        age = now - self.last_event_ts
        if age > self.FRESHNESS_CAP:
            return False
        if self.completed == self.total:
            return age <= self.GRACE_SECONDS
        return True
