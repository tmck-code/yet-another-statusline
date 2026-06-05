"""RunningSubagent and RunningSubagents — active sub-agent discovery."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from yas.constants import CLAUDE_DIR, _sanitize


def read_last_prompt_ts(session_id: str) -> float | None:
    '''Return the last UserPromptSubmit timestamp for session_id, or None.

    Reads the yas-last-prompt.json state file (a JSON map of session_id →
    float epoch seconds) from CLAUDE_DIR.  Returns None when the file is
    missing, unreadable, contains invalid JSON, or does not include an entry
    for session_id.  Never raises.
    '''
    try:
        state = CLAUDE_DIR / 'yas-last-prompt.json'
        text = state.read_text()
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        val = data.get(session_id)
        if val is None:
            return None
        return float(val)
    except Exception:
        return None


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
    end_ts:        float                 = 0.0  # end_turn timestamp; Done iff end_ts > 0
    mtime:         float                 = 0.0  # transcript last-modified time (st_mtime)


@dataclass
class RunningSubagents:
    subagents: list[RunningSubagent] = field(default_factory=list)

    # Cohort grace: seconds after the last end_ts before a fully-Done section retires
    COHORT_GRACE_SECONDS = 20
    # Janitor horizon: total-silence threshold to sweep a dirty cohort (no end_turn);
    # also the recency-window fallback when no prompt-marker is available
    JANITOR_HORIZON_SECONDS = 60
    # Liveness window: silence threshold for "still writing" vs "idle/done" (straggler keep)
    LIVENESS_WINDOW_SECONDS = 30
    # Keep the old name as an alias so existing code that references it still works
    STALE_SECONDS = LIVENESS_WINDOW_SECONDS

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
        subagents: list[RunningSubagent] = []
        try:
            for meta in subagents_dir.glob('*.meta.json'):
                agent_type = ''
                description = ''
                try:
                    data = json.loads(meta.read_text())
                    agent_type = _sanitize(data.get('agentType', '') or '')
                    description = _sanitize(data.get('description', '') or '')
                except Exception:
                    continue

                jsonl = meta.with_suffix('').with_suffix('.jsonl')
                if not jsonl.is_file():
                    continue
                try:
                    mtime = jsonl.stat().st_mtime
                except OSError:
                    continue

                billed_in, cache_read_in, output, first_ts, model, last_activity, end_ts = cls._parse_transcript(jsonl)
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
                    end_ts          = end_ts,
                    mtime           = mtime,
                ))
        except OSError:
            pass
        subagents.sort(key=lambda s: s.first_timestamp)
        return cls(subagents=subagents)

    def visible(self, now: float, last_prompt_ts: float | None) -> list[RunningSubagent]:
        '''Compute the turn-scoped cohort visible in the statusline.

        When last_prompt_ts is provided (from the prompt-boundary hook), an
        agent is a candidate if it started this turn (first_timestamp >=
        last_prompt_ts) OR it is still being written (transcript written within
        LIVENESS_WINDOW_SECONDS), which keeps stragglers from the previous turn
        that haven't finished yet.  A still-running agent (end_ts == 0) that is
        actively writing is always included regardless.

        When last_prompt_ts is None (hook unavailable), fall back to the
        JANITOR_HORIZON_SECONDS recency window: include any agent written within
        60 s, or still running (end_ts == 0).

        After computing candidates, retirement rules apply:
        - If all candidates are Done (end_ts > 0): hide once
          now - max(end_ts) > COHORT_GRACE_SECONDS (20 s clean-retire).
        - Otherwise (dirty cohort): hide once every member's transcript has
          been silent for JANITOR_HORIZON_SECONDS (60 s janitor sweep).
        '''
        if last_prompt_ts is not None:
            # Turn-scoped membership (Tasks 3.2 + 3.3)
            candidates = [
                sub for sub in self.subagents
                if sub.first_timestamp >= last_prompt_ts
                or now - sub.mtime <= self.LIVENESS_WINDOW_SECONDS
            ]
        else:
            # No-marker fallback (Task 3.4): recency window
            candidates = [
                sub for sub in self.subagents
                if now - sub.mtime <= self.JANITOR_HORIZON_SECONDS
                or sub.end_ts == 0
            ]

        if not candidates:
            return []

        # Retirement logic (Task 3.3)
        if all(sub.end_ts > 0 for sub in candidates):
            # Fully-Done cohort: retire once the grace window expires
            if now - max(sub.end_ts for sub in candidates) > self.COHORT_GRACE_SECONDS:
                return []
        else:
            # Dirty cohort: janitor sweep when all transcripts have gone silent
            if all(now - sub.mtime > self.JANITOR_HORIZON_SECONDS for sub in candidates):
                return []

        return candidates

    @staticmethod
    def _parse_transcript(jsonl: Path) -> tuple[int, int, int, float, str, tuple[str, str, dict[str, object]], float]:
        seen: set[str] = set()
        billed_in    = 0
        cache_read_in = 0
        output       = 0
        first_ts     = 0.0
        end_ts       = 0.0
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
                            raw_inp = item.get('input') or {}
                            inp = {
                                k: _sanitize(v) if isinstance(v, str) else v
                                for k, v in raw_inp.items()
                            } if isinstance(raw_inp, dict) else {}
                            last_activity = ('tool_use', _sanitize(item.get('name', '') or ''), inp)
                        elif kind == 'thinking':
                            last_activity = ('thinking', '', {})
                        elif kind == 'text':
                            last_activity = ('text', '', {})
                    try:
                        if msg.get('stop_reason') == 'end_turn':
                            ts = d.get('timestamp', '')
                            if ts:
                                end_ts = _parse_iso_to_epoch(ts)
                    except (ValueError, TypeError):
                        pass
        except OSError:
            pass
        return billed_in, cache_read_in, output, first_ts, model, last_activity, end_ts
