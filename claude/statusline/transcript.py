"""Transcript scanning + the live-session derived data: skills, tasks, subagents.

The single-pass `TranscriptScan` produces the three aggregates the renderer
needs (loaded skills, task list, token usage) in *one* read of the JSONL
transcript — replacing three independent full-file scans the original code did.

`_scan_transcript` is the public entry. It caches the most recent scan keyed
on (path, size, mtime_ns), so the three projection classmethods called within
one wide render share ONE scan. For real Claude session transcripts (those
under `config.CLAUDE_DIR/projects`) it tails *incrementally*: a persisted byte
offset + the full scan state lives under `config.CLAUDE_DIR/statusline-scan/`,
keyed by an sha1 of the path. The full scan is the always-correct fallback —
any anomaly (corrupt state, schema bump, path/inode change, offset past EOF)
forces a full re-scan, so the worst case is "no speedup this render," never
"wrong stats." YAS_NO_INCREMENTAL is the kill switch.

`RunningSubagents.from_session` is a separate scanner — it reads
`config.CLAUDE_DIR/projects/<slug>/<session>/subagents/*.jsonl` (the subagent
transcripts CC writes out) and surfaces stale-aware per-subagent stats.

This is the largest single module in the split — ~530 lines of carefully
tested algorithm. The Vantage Swift port will mirror this exact shape.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from statusline import config
from statusline.models import _as_float, _as_int, _as_str
from statusline.textutil import _atomic_write_text


@dataclass
class LoadedSkills:
    names: list[str] = field(default_factory=list)

    @classmethod
    def from_transcript(cls, transcript_path: str) -> LoadedSkills:
        return _scan_transcript(transcript_path).loaded_skills()


@dataclass
class RunningSubagent:
    agent_type: str
    description: str
    billed_in: int
    output: int
    first_timestamp: float  # epoch seconds; baseline for live duration
    model:         str                   = ''
    cache_read_in: int                   = 0
    total_input:   int                   = 0
    last_activity: tuple[str, str, dict[str, object]] = field(default_factory=lambda: ('', '', {}))


@dataclass
class RunningSubagents:
    subagents: list[RunningSubagent] = field(default_factory=list)

    STALE_SECONDS = 20

    @classmethod
    def from_session(cls, session_id: str, project_dir: str) -> RunningSubagents:
        if not session_id or not project_dir:
            return cls()
        # Match Claude Code's projects/ dir convention: replace every non-
        # alphanumeric character with '-'. Works on both Unix
        # ('/home/user/my-project' -> '-home-user-my-project') and Windows
        # ('C:\\Users\\desal\\Project' -> 'C--Users-desal-Project'). The old
        # logic was Unix-only because it normalized only '/' and relied on a
        # leading slash producing the '-' prefix that Claude Code uses on
        # Unix; on Windows paths start with a drive letter (no leading '-'
        # in CC's dir name) so the f-string prefix gave a wrong path.
        project_slug = re.sub(r'[^A-Za-z0-9]', '-', project_dir)
        subagents_dir = config.CLAUDE_DIR / 'projects' / project_slug / session_id / 'subagents'
        if not subagents_dir.is_dir():
            return cls()
        now = time.time()
        subagents: list[RunningSubagent] = []
        try:
            for meta in subagents_dir.glob('*.meta.json'):
                agent_type = ''
                description = ''
                try:
                    data = json.loads(meta.read_text())
                    agent_type = data.get('agentType', '')
                    description = data.get('description', '')
                except Exception:
                    continue

                jsonl = meta.with_suffix('').with_suffix('.jsonl')
                if not jsonl.is_file():
                    continue
                try:
                    mtime = jsonl.stat().st_mtime
                    if now - mtime > cls.STALE_SECONDS:
                        continue
                except OSError:
                    continue

                billed_in, cache_read_in, output, first_ts, model, last_activity = cls._parse_transcript(jsonl)
                subagents.append(RunningSubagent(
                    agent_type      = agent_type,
                    description     = description,
                    billed_in       = billed_in,
                    output          = output,
                    first_timestamp = first_ts,
                    model           = model,
                    cache_read_in   = cache_read_in,
                    total_input     = billed_in + cache_read_in,
                    last_activity   = last_activity,
                ))
        except OSError:
            pass
        subagents.sort(key=lambda s: s.first_timestamp)
        return cls(subagents=subagents)

    @staticmethod
    def _parse_transcript(jsonl: Path) -> tuple[int, int, int, float, str, tuple[str, str, dict[str, object]]]:
        seen: set[str] = set()
        billed_in    = 0
        cache_read_in = 0
        output       = 0
        first_ts     = 0.0
        model        = ''
        last_activity: tuple[str, str, dict[str, object]] = ('', '', {})
        try:
            with jsonl.open('r', errors='ignore') as fh:
                for ln in fh:
                    if first_ts == 0.0 and '"timestamp"' in ln:
                        try:
                            d = json.loads(ln)
                            ts = d.get('timestamp', '')
                            if ts:
                                first_ts = _parse_iso_to_epoch(ts)
                        except (ValueError, TypeError):
                            pass
                    if '"usage"' not in ln or '"assistant"' not in ln:
                        continue
                    try:
                        d = json.loads(ln)
                    except (ValueError, TypeError):
                        continue
                    msg = d.get('message') or {}
                    mid = msg.get('id')
                    if not mid or mid in seen:
                        continue
                    seen.add(mid)
                    if not model:
                        m = msg.get('model') or ''
                        if m:
                            model = m
                    u = msg.get('usage') or {}
                    billed_in     += (u.get('input_tokens', 0) or 0) + (u.get('cache_creation_input_tokens', 0) or 0)
                    cache_read_in += u.get('cache_read_input_tokens', 0) or 0
                    output        += u.get('output_tokens', 0) or 0
                    content = msg.get('content') or []
                    if content:
                        item = content[-1]
                        kind = item.get('type', '')
                        if kind == 'tool_use':
                            last_activity = ('tool_use', item.get('name', ''), item.get('input') or {})
                        elif kind == 'thinking':
                            last_activity = ('thinking', '', {})
                        elif kind == 'text':
                            last_activity = ('text', '', {})
        except OSError:
            pass
        return billed_in, cache_read_in, output, first_ts, model, last_activity


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
        return _scan_transcript(transcript_path).task_list()

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


@dataclass
class TranscriptUsage:
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_transcript(cls, transcript_path: str) -> TranscriptUsage:
        return _scan_transcript(transcript_path).transcript_usage()

    @property
    def billed_in(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens

    @property
    def cache_read(self) -> int:
        return self.cache_read_input_tokens

    @property
    def out(self) -> int:
        return self.output_tokens


# Regexes for skill detection in a transcript line. Module-level so they are
# compiled once per process instead of once per scan (the legacy code rebuilt
# them on every call).
_SKILL_PAT      = re.compile(r'"name"\s*:\s*"Skill"[^}]*?"skill"\s*:\s*"([^"]+)"')
_READ_PAT       = re.compile(r'"name"\s*:\s*"Read"[^}]*?"file_path"\s*:\s*"([^"]+)"')
_SKILL_PATH_PAT = re.compile(r'/skills/([^/"]+)/SKILL\.md$')


@dataclass
class TranscriptScan:
    '''Single pass over a session transcript JSONL, producing the three
    aggregates the renderer needs (loaded skills, task list, token usage) in
    one read instead of three independent full-file scans.

    Each line is decoded with json at most once, and only when a cheap
    substring pre-check matches, exactly as the three legacy scanners did
    individually. The projection methods rebuild the public LoadedSkills /
    TaskList / TranscriptUsage dataclasses so existing callers and tests see
    identical results.
    '''
    skill_names:                 dict[str, None] = field(default_factory=dict)
    usage_seen:                  set[str]        = field(default_factory=set)
    input_tokens:                int             = 0
    cache_creation_input_tokens: int             = 0
    cache_read_input_tokens:     int             = 0
    output_tokens:               int             = 0
    by_id:                       dict[int, Task] = field(default_factory=dict)
    next_id:                     int             = 1
    last_event_ts:               float           = 0.0

    @classmethod
    def scan_full(cls, transcript_path: str) -> TranscriptScan:
        'Read the whole transcript from the start. Always correct; the fallback for incremental tailing.'
        scan = cls()
        if not transcript_path:
            return scan
        p = Path(transcript_path)
        if not p.is_file():
            return scan
        try:
            with p.open('rb') as fh:
                data = fh.read()
        except OSError:
            return cls()
        scan._process_bytes(data)
        return scan

    def _process_bytes(self, data: bytes) -> int:
        '''Fold every complete (newline-terminated) line in `data` into the scan
        and return the bytes consumed (up to and including the last newline). Any
        unterminated trailing fragment is left unprocessed, so a mid-write final
        line is never counted. Shared by the full and incremental paths so their
        results are identical by construction.'''
        consumed = data.rfind(b'\n') + 1
        for raw in data[:consumed].split(b'\n'):
            if raw:
                self.process_line(raw.decode('utf-8', 'ignore'))
        return consumed

    def process_line(self, line: str) -> None:
        'Fold a single transcript line into all three aggregates (skills, tasks, usage).'
        if '"Skill"' in line:
            for m in _SKILL_PAT.finditer(line):
                self.skill_names.setdefault(m.group(1), None)
        if '"Read"' in line and 'SKILL.md' in line:
            for m in _READ_PAT.finditer(line):
                sm = _SKILL_PATH_PAT.search(m.group(1))
                if sm:
                    self.skill_names.setdefault(sm.group(1), None)
        need_usage = '"usage"' in line and '"assistant"' in line
        need_task  = '"TaskCreate"' in line or '"TaskUpdate"' in line
        if not (need_usage or need_task):
            return
        try:
            d = json.loads(line)
        except (ValueError, TypeError):
            return
        if not isinstance(d, dict):
            return
        if need_usage:
            self._apply_usage(d)
        if need_task:
            self._apply_tasks(d)

    def _apply_usage(self, d: dict[str, object]) -> None:
        msg = d.get('message')
        if not isinstance(msg, dict):
            return
        mid = msg.get('id')
        if not mid or mid in self.usage_seen:
            return
        self.usage_seen.add(mid)
        u_raw = msg.get('usage')
        u = u_raw if isinstance(u_raw, dict) else {}
        self.input_tokens                += _as_int(u.get('input_tokens'))
        self.cache_creation_input_tokens += _as_int(u.get('cache_creation_input_tokens'))
        self.cache_read_input_tokens     += _as_int(u.get('cache_read_input_tokens'))
        self.output_tokens               += _as_int(u.get('output_tokens'))

    def _apply_tasks(self, d: dict[str, object]) -> None:
        msg = d.get('message')
        if not isinstance(msg, dict):
            return
        raw_ts = d.get('timestamp', '')
        ts = _parse_iso_to_epoch(raw_ts) if isinstance(raw_ts, str) else 0.0
        content = msg.get('content', [])
        if not isinstance(content, list):
            return
        for c in content:
            if not isinstance(c, dict) or c.get('type') != 'tool_use':
                continue
            name = c.get('name', '')
            inp  = c.get('input') or {}
            if not isinstance(inp, dict):
                continue
            if name == 'TaskCreate':
                subj = inp.get('subject', '') or ''
                af   = inp.get('activeForm', '') or subj
                self.by_id[self.next_id] = Task(id=self.next_id, subject=subj, active_form=af, status='pending')
                self.next_id += 1
                if ts > self.last_event_ts:
                    self.last_event_ts = ts
            elif name == 'TaskUpdate':
                try:
                    tid = int(inp.get('taskId', '0'))
                except (TypeError, ValueError):
                    continue
                t = self.by_id.get(tid)
                if not t:
                    continue
                new_status = inp.get('status')
                if new_status in ('pending', 'in_progress', 'completed'):
                    t.status = new_status
                if 'activeForm' in inp and inp['activeForm']:
                    t.active_form = inp['activeForm']
                if 'subject' in inp and inp['subject']:
                    t.subject = inp['subject']
                if ts > self.last_event_ts:
                    self.last_event_ts = ts

    def loaded_skills(self) -> LoadedSkills:
        return LoadedSkills(names=list(self.skill_names))

    def transcript_usage(self) -> TranscriptUsage:
        return TranscriptUsage(
            input_tokens                = self.input_tokens,
            cache_creation_input_tokens = self.cache_creation_input_tokens,
            cache_read_input_tokens     = self.cache_read_input_tokens,
            output_tokens               = self.output_tokens,
        )

    def task_list(self) -> TaskList:
        # Fresh Task objects so a cached scan can't be mutated through a projection.
        tasks = [
            Task(id=t.id, subject=t.subject, active_form=t.active_form, status=t.status)
            for t in (self.by_id[k] for k in sorted(self.by_id))
        ]
        return TaskList(tasks=tasks, last_event_ts=self.last_event_ts)

    def to_state(self) -> dict[str, object]:
        'Serialize the accumulator for incremental-tailing persistence.'
        return {
            'skills':  list(self.skill_names),
            'seen':    list(self.usage_seen),
            'in':      self.input_tokens,
            'cc':      self.cache_creation_input_tokens,
            'cr':      self.cache_read_input_tokens,
            'out':     self.output_tokens,
            'tasks':   [{'id': t.id, 'subject': t.subject, 'active_form': t.active_form, 'status': t.status}
                        for t in (self.by_id[k] for k in sorted(self.by_id))],
            'next_id': self.next_id,
            'last_ts': self.last_event_ts,
        }

    @classmethod
    def from_state(cls, d: dict[str, object]) -> TranscriptScan:
        'Rehydrate an accumulator persisted by to_state (defensive against malformed data).'
        scan = cls()
        skills = d.get('skills')
        if isinstance(skills, list):
            scan.skill_names = {s: None for s in skills if isinstance(s, str)}
        seen = d.get('seen')
        if isinstance(seen, list):
            scan.usage_seen = {s for s in seen if isinstance(s, str)}
        scan.input_tokens                = _as_int(d.get('in'))
        scan.cache_creation_input_tokens = _as_int(d.get('cc'))
        scan.cache_read_input_tokens     = _as_int(d.get('cr'))
        scan.output_tokens               = _as_int(d.get('out'))
        tasks = d.get('tasks')
        if isinstance(tasks, list):
            for t in tasks:
                if isinstance(t, dict):
                    tid = _as_int(t.get('id'))
                    scan.by_id[tid] = Task(
                        id          = tid,
                        subject     = _as_str(t.get('subject')),
                        active_form = _as_str(t.get('active_form')),
                        status      = _as_str(t.get('status'), 'pending'),
                    )
        ni = d.get('next_id')
        scan.next_id = ni if isinstance(ni, int) and ni >= 1 else (max(scan.by_id, default=0) + 1)
        scan.last_event_ts = _as_float(d.get('last_ts'))
        return scan


# One-slot, file-identity-keyed cache so the three projections requested within a
# single wide render share ONE scan. Keyed on (path, size, mtime_ns).
_SCAN_CACHE: tuple[tuple[str, int, int], TranscriptScan] | None = None
_SCAN_STATE_V = 1


def _incremental_enabled(p: Path) -> bool:
    '''Incremental tailing applies only to real Claude session transcripts (those
    under config.CLAUDE_DIR/projects) — this keeps state writes out of arbitrary
    directories and out of the tmp_path-only tests. YAS_NO_INCREMENTAL is a kill
    switch that forces the always-correct full scan.'''
    if os.environ.get('YAS_NO_INCREMENTAL'):
        return False
    try:
        return p.resolve().is_relative_to((config.CLAUDE_DIR / 'projects').resolve())
    except (OSError, ValueError):
        return False


def _scan_state_path(p: Path) -> Path:
    h = hashlib.sha1(str(p).encode('utf-8')).hexdigest()[:16]
    return config.CLAUDE_DIR / 'statusline-scan' / f'{h}.json'


def _resume_point(state_path: Path, p: Path, st: os.stat_result) -> tuple[TranscriptScan, int]:
    '''(scan, start_offset) to resume from, or (empty, 0) to force a full re-scan
    on any mismatch: missing/corrupt state, schema bump, path or inode change
    (rotation/replacement), or an offset past EOF (truncation/shrink).'''
    try:
        d = json.loads(state_path.read_text())
    except (OSError, ValueError):
        return TranscriptScan(), 0
    if (not isinstance(d, dict) or d.get('v') != _SCAN_STATE_V
            or d.get('path') != str(p) or d.get('inode') != st.st_ino):
        return TranscriptScan(), 0
    offset = d.get('offset')
    scan_d = d.get('scan')
    if not isinstance(offset, int) or offset < 0 or offset > st.st_size or not isinstance(scan_d, dict):
        return TranscriptScan(), 0
    return TranscriptScan.from_state(scan_d), offset


def _save_scan_state(state_path: Path, p: Path, st: os.stat_result, offset: int, scan: TranscriptScan) -> None:
    _atomic_write_text(state_path, json.dumps({
        'v':      _SCAN_STATE_V,
        'path':   str(p),
        'inode':  st.st_ino,
        'offset': offset,
        'scan':   scan.to_state(),
    }))


def _scan_with_state(p: Path, st: os.stat_result) -> TranscriptScan:
    'Read only the bytes appended since the persisted offset; persist the advanced state.'
    state_path = _scan_state_path(p)
    scan, start = _resume_point(state_path, p, st)
    new_offset = start
    if start < st.st_size:
        with p.open('rb') as fh:
            fh.seek(start)
            data = fh.read()
        new_offset = start + scan._process_bytes(data)
    if new_offset != start:
        _save_scan_state(state_path, p, st, new_offset, scan)
    return scan


def _scan_transcript(transcript_path: str) -> TranscriptScan:
    '''Cached single-pass scan shared by the three projection classmethods within
    one render. For real session transcripts it tails incrementally (reading only
    newly-appended bytes via a persisted accumulator); everything else, and any
    anomaly, falls back to the always-correct full scan.'''
    global _SCAN_CACHE
    if not transcript_path:
        return TranscriptScan()
    p = Path(transcript_path)
    if not p.is_file():
        return TranscriptScan()
    try:
        st = p.stat()
    except OSError:
        return TranscriptScan()
    key = (str(p), st.st_size, st.st_mtime_ns)
    cached = _SCAN_CACHE
    if cached is not None and cached[0] == key:
        return cached[1]
    if _incremental_enabled(p):
        try:
            scan = _scan_with_state(p, st)
        except Exception:
            scan = TranscriptScan.scan_full(transcript_path)
    else:
        scan = TranscriptScan.scan_full(transcript_path)
    _SCAN_CACHE = (key, scan)
    return scan
