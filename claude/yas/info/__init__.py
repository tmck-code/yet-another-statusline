"""SessionView — lazy gather seam for all derived session state.

All I/O is deferred to first access via @cached_property. Callers
construct a SessionView and read only the fields they need; unread
fields never touch the filesystem.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import cached_property

from yas.config import Config
from yas.info.git import GitInfo
from yas.info.openspec import OpenSpec
from yas.session import SessionInfo
from yas.info.skills import LoadedSkills
from yas.info.subagents import RunningSubagents
from yas.info.tasks import TaskList
from yas.tokens import compute_session_cost
from yas.info.transcript import TranscriptUsage


# ---------------------------------------------------------------------------
# Elapsed formatting
# ---------------------------------------------------------------------------

def _fmt_duration_ms(ms: int) -> str:
    """Format a duration in milliseconds into a human-readable string.

    Returns '' for zero ms, 'Nm' for under an hour, 'HhMm' for >= 1 h.
    """
    if ms <= 0:
        return ''
    total_m = ms // 60_000
    h = total_m // 60
    m = total_m % 60
    if h == 0:
        return f'{m}m'
    return f'{h}h{m}m'


def _fmt_elapsed_clock(ms: int) -> str:
    """Format a duration in milliseconds as H:MM:SS clock time.

    Returns '' for zero or negative ms; otherwise H:MM:SS (e.g. '0:13:01').
    """
    if ms <= 0:
        return ''
    s   = ms // 1000
    h   = s // 3600
    m   = (s % 3600) // 60
    sec = s % 60
    return f'{h}:{m:02d}:{sec:02d}'


def _fmt_elapsed(mtime: float | None, now: float) -> str:
    """Format seconds-since-mtime as a human-readable string.

    Kept as a wrapper around _fmt_duration_ms for backward-compatible callers.
    Returns '' for None mtime, 'Nm' for under an hour, 'HhMm' for >= 1 h.
    """
    if mtime is None:
        return ''
    return _fmt_duration_ms(int(max(0, now - mtime) * 1000))


# ---------------------------------------------------------------------------
# SessionView
# ---------------------------------------------------------------------------

@dataclass
class SessionView:
    session: SessionInfo
    cfg:     Config
    now:     float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Leaf readers — each delegates to its existing classmethod
    # ------------------------------------------------------------------

    @cached_property
    def git(self) -> GitInfo:
        return GitInfo.from_cwd(self.session.cwd)

    @cached_property
    def skills(self) -> LoadedSkills:
        return LoadedSkills.from_transcript(self.session.transcript_path)

    @cached_property
    def subagents(self) -> RunningSubagents:
        return RunningSubagents.from_session(
            self.session.session_id,
            self.session.workspace.project_dir,
        )

    @cached_property
    def tasks(self) -> TaskList:
        return TaskList.from_session(self.session.transcript_path)

    @cached_property
    def transcript_usage(self) -> TranscriptUsage:
        return TranscriptUsage.from_transcript(self.session.transcript_path)

    @cached_property
    def changes(self) -> list[tuple[str, int, int]]:
        return OpenSpec.from_cwd(self.session.cwd).changes

    # ------------------------------------------------------------------
    # Derived fields
    # ------------------------------------------------------------------

    @cached_property
    def session_cost(self) -> float:
        return compute_session_cost(self.session.model, self.transcript_usage)

    @cached_property
    def session_inout(self) -> int:
        usage = self.transcript_usage
        total = usage.billed_in + usage.cache_read + usage.out
        for s in self.subagents.subagents:
            total += s.total_input + s.output
        return total

    @cached_property
    def cache_countdown(self) -> tuple[float, int] | None:
        """Remaining cache TTL as (seconds_remaining, elapsed_pct) or None.

        Returns None when there is no cache anchor, the cache has already
        expired, or the TTL is unknown. elapsed_pct is clamped to [0, 100]
        and represents how much of the TTL has been consumed (0 = fresh,
        100 = expired). Holds no ANSI or render geometry.

        This is inspired/taken directly from the implementation by @rodboev here:
        https://gist.github.com/rodboev/108ae70ea338bebd7e96304bc797d9b8
        """
        u = self.transcript_usage
        cache_anchor_epoch = u.cache_anchor_epoch
        cache_ttl = u.cache_ttl
        if cache_anchor_epoch == 0.0 or cache_ttl == 0:
            return None
        remaining = cache_ttl - (self.now - cache_anchor_epoch)
        if remaining <= 0:
            return None
        elapsed_pct = max(0, min(100, 100 - round(remaining * 100 / cache_ttl)))
        return (remaining, elapsed_pct)

    @cached_property
    def elapsed(self) -> str:
        return _fmt_elapsed_clock(self.session.cost.total_duration_ms)
