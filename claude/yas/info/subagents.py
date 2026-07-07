"""RunningSubagent and RunningSubagents — active sub-agent discovery."""

from __future__ import annotations

import json
import re
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


def parse_transcript(jsonl: Path) -> tuple[int, int, int, float, str, tuple[str, str, dict[str, object]], float]:
    """Parse one agent-*.jsonl transcript into the subagent metric tuple.

    Module-level so the workflow cohort reader (info/workflows.py) can call the
    identical token/activity/Done logic without duplicating it. Returns
    ``(billed_in, cache_read_in, output, first_ts, model, last_activity, end_ts)``.
    Never raises; an unreadable transcript yields zeroes.
    """
    seen: set[str] = set()
    billed_in    = 0
    cache_read_in = 0
    output       = 0
    first_ts     = 0.0
    end_ts       = 0.0
    model        = ''
    last_activity: tuple[str, str, dict[str, object]] = ('', '', {})
    # Shape of the most recent assistant+usage line, used for the terminal-
    # text Done fallback after the loop (see below). Overwritten each line so
    # only the LAST assistant message decides — interstitial null-stop text
    # lines mid-stream are superseded by whatever assistant line follows.
    last_stop:     str | None = None
    last_has_tool             = False
    last_has_text             = False
    last_ts                   = 0.0
    last_content: list[str]   = []  # content from the final terminal-state line
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
                # Terminal-state check runs on EVERY assistant+usage line,
                # independent of message-id dedup. Streaming writes the same
                # message.id several times (early partials with
                # stop_reason: null, a final write with end_turn); the dedup
                # below must not let an already-seen id suppress this capture.
                # Last-write-wins: a later end_turn overwrites an earlier
                # end_ts, and a later NON-terminal line clears it — a subagent
                # can be resumed after its turn ends (SendMessage to a warm
                # agent), and the stale end_ts would render a working agent as
                # Done. Done therefore means the transcript currently ENDS in
                # an ended turn; a resumed agent that finishes again goes Done
                # at the later time via a new end_turn or a post-loop fallback.
                try:
                    stop   = msg.get('stop_reason')
                    ts_raw = d.get('timestamp', '')
                    line_ts = _parse_iso_to_epoch(ts_raw) if ts_raw else 0.0
                    if stop == 'end_turn' and line_ts:
                        end_ts = line_ts
                    elif stop != 'end_turn':
                        end_ts = 0.0
                    # Record this line's shape for the post-loop fallback.
                    # Runs pre-dedup so the final full write of a streamed
                    # message is always observed even if its id was seen.
                    cont = msg.get('content') or []
                    last_has_tool = any(isinstance(b, dict) and b.get('type') == 'tool_use' for b in cont)
                    last_has_text = any(isinstance(b, dict) and b.get('type') == 'text'     for b in cont)
                    last_stop, last_ts = stop, line_ts
                    last_content = cont
                except (ValueError, TypeError, AttributeError):
                    pass
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
                    # Prefer the last tool_use block anywhere in the message;
                    # a trailing text narration must not mask an actual tool
                    # call (Claude often emits [text, tool_use, text]).  Only
                    # when no tool_use exists do we fall back to the first
                    # non-empty line of the last text block, then thinking.
                    last_tool = None
                    last_text = None
                    for item in content:
                        kind = item.get('type', '')
                        if kind == 'tool_use':
                            last_tool = item
                        elif kind == 'text':
                            last_text = item
                    if last_tool is not None:
                        raw_inp = last_tool.get('input') or {}
                        inp = {
                            k: _sanitize(v) if isinstance(v, str) else v
                            for k, v in raw_inp.items()
                        } if isinstance(raw_inp, dict) else {}
                        last_activity = ('tool_use', _sanitize(last_tool.get('name', '') or ''), inp)
                    elif last_text is not None:
                        snippet = ''
                        for line in str(last_text.get('text', '') or '').splitlines():
                            stripped = line.strip()
                            if stripped:
                                snippet = _sanitize(stripped)
                                break
                        last_activity = ('text', snippet, {})
                    else:
                        last_activity = ('thinking', '', {})
    except OSError:
        pass
    # Terminal-text Done fallback. Some sidechain (sub-agent) transcripts
    # never emit stop_reason: "end_turn" — every assistant line is either
    # "tool_use" or null, including the final result message. A finished
    # agent's LAST assistant line is then terminal text: a text block with no
    # tool_use awaiting a result. A still-running agent's last assistant line
    # is a tool_use (or it is mid-streaming), so this cannot fire once work
    # is genuinely done. Only the last line is considered, so interstitial
    # null-stop text mid-stream never triggers it.
    if end_ts == 0.0 and last_ts and last_has_text and not last_has_tool and last_stop != 'tool_use':
        end_ts = last_ts
    # Structured-output done detection. Workflow agents finish by calling
    # StructuredOutput as their terminal action. The final assistant line may
    # carry stop_reason: "tool_use" OR stop_reason: null (a streamed write whose
    # stop never got finalized on disk) — both mean done. The StructuredOutput
    # call IS the completion marker; a later retry (schema mismatch) would append
    # further assistant lines, so only a truly terminal call reaches here.
    if end_ts == 0.0 and last_ts and last_has_tool and last_stop in ('tool_use', None):
        # Check if the only tool_use in the final message is StructuredOutput.
        # This is a completion signal, not an intermediate tool call.
        for item in last_content:
            if isinstance(item, dict) and item.get('type') == 'tool_use':
                if item.get('name') == 'StructuredOutput':
                    end_ts = last_ts
                    break
    return billed_in, cache_read_in, output, first_ts, model, last_activity, end_ts


class RunningSubagent:
    __slots__ = (
        'agent_type', 'description', 'billed_in', 'output', 'first_timestamp',
        'model', 'cache_read_in', 'total_input', 'last_activity', 'end_ts',
        'mtime', 'agent_id',
    )

    def __init__(
        self,
        agent_type:      str,
        description:     str,
        billed_in:       int,
        output:          int,
        first_timestamp: float,  # epoch seconds; baseline for live duration
        model:           str = '',
        cache_read_in:   int = 0,
        total_input:     int = 0,
        last_activity:   tuple[str, str, dict[str, object]] | None = None,
        end_ts:          float = 0.0,  # end_turn ts, else terminal-text ts; Done iff > 0
        mtime:           float = 0.0,  # transcript last-modified time (st_mtime)
        agent_id:        str = '',     # transcript filename stem; matches run-JSON agentId (workflow cohort)
    ) -> None:
        self.agent_type      = agent_type
        self.description      = description
        self.billed_in        = billed_in
        self.output           = output
        self.first_timestamp  = first_timestamp
        self.model            = model
        self.cache_read_in    = cache_read_in
        self.total_input      = total_input
        self.last_activity    = last_activity if last_activity is not None else ('', '', {})
        self.end_ts           = end_ts
        self.mtime            = mtime
        self.agent_id         = agent_id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RunningSubagent):
            return NotImplemented
        return self._key() == other._key()

    def _key(self) -> tuple[object, ...]:
        return (
            self.agent_type, self.description, self.billed_in, self.output,
            self.first_timestamp, self.model, self.cache_read_in, self.total_input,
            self.last_activity, self.end_ts, self.mtime, self.agent_id,
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (f'RunningSubagent(agent_type={self.agent_type!r}, description={self.description!r}, '
                f'billed_in={self.billed_in}, output={self.output}, first_timestamp={self.first_timestamp}, '
                f'model={self.model!r}, cache_read_in={self.cache_read_in}, total_input={self.total_input}, '
                f'last_activity={self.last_activity!r}, end_ts={self.end_ts}, mtime={self.mtime}, '
                f'agent_id={self.agent_id!r})')


class RunningSubagents:
    __slots__ = ('subagents',)

    def __init__(self, subagents: list[RunningSubagent] | None = None) -> None:
        self.subagents = subagents if subagents is not None else []

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RunningSubagents):
            return NotImplemented
        return self.subagents == other.subagents

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'RunningSubagents(subagents={self.subagents!r})'

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
        # Thin delegator to the module-level parse_transcript, kept so existing
        # callers/tests referencing RunningSubagents._parse_transcript still work.
        return parse_transcript(jsonl)
