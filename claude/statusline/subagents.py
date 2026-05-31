"""RunningSubagent and RunningSubagents — active sub-agent discovery."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from statusline.constants import CLAUDE_DIR


def _parse_iso_to_epoch(ts: str) -> float:
    try:
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


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
        subagents_dir = CLAUDE_DIR / 'projects' / project_slug / session_id / 'subagents'
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
