"""Current activity of the main Claude session's transcript.

The subagent parser (`yas.info.subagents`) already folds each `agent-*.jsonl`
into a last-activity kind plus the timestamp of the first line that carried it.
The main transcript has the same shape, so the same fold serves it here: a
`thinking` kind means the model is inside a thinking block, and `since` is when
that block began (used for the thinking timer on the synthetic main row).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from yas.info.subagents import parse_transcript

if TYPE_CHECKING:
    from yas.info.parsecache import TranscriptCache


@dataclass(frozen=True)
class MainActivity:
    'Last activity of the main thread, plus when that activity began.'
    first_ts: float = 0.0
    kind:     str   = ''        # 'tool_use' | 'text' | 'thinking' | ''
    since:    float = 0.0       # epoch of the first line of the current message
    mtime:    float = 0.0       # transcript mtime
    activity: tuple[str, str, dict[str, object]] = ('', '', {})  # full last_activity tuple

    @property
    def thinking(self) -> bool:
        return self.kind == 'thinking' and self.since > 0

    def thinking_s(self, now: float) -> float:
        'Seconds spent thinking, or 0 when the last activity is not thinking.'
        return max(0.0, now - self.since) if self.thinking else 0.0


def read_main_activity(
    transcript_path: str | None,
    *,
    cache: TranscriptCache | None = None,
) -> MainActivity:
    'Fold the main transcript; never raises (an unreadable file yields an empty activity).'
    if not transcript_path:
        return MainActivity()
    try:
        path = Path(transcript_path)
        st = path.stat()
    except OSError:
        return MainActivity()
    try:
        parsed = parse_transcript(path, cache=cache, st=st)
    except Exception:
        return MainActivity()
    _billed, _cache_read, _out, first_ts, _model, last_activity, _end, _run_start, last_ts = parsed
    return MainActivity(
        first_ts   = first_ts,
        kind       = last_activity[0],
        since      = last_ts,
        mtime      = st.st_mtime,
        activity   = last_activity,
    )
