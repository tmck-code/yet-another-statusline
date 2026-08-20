"""SessionView — lazy gather seam for all derived session state; I/O deferred to first access via @cached_property."""

from __future__ import annotations

import time
from functools import cached_property

from yas.config import Config
from yas.info.git import GitInfo
from yas.info.openspec import OpenSpec
from yas.session import SessionInfo
from yas.info.skills import LoadedSkills
from yas.info.subagents import RunningSubagents
from yas.info.workflows import RunningWorkflows
from yas.info.tasks import TaskList
from yas.tokens import compute_session_cost
from yas.info.transcript import TranscriptUsage
from yas.info.toolcounts import ToolCounts
from yas.info.clear import read_clear_epoch
from yas.info.parsecache import TranscriptCache


# ---------------------------------------------------------------------------
# Elapsed formatting
# ---------------------------------------------------------------------------

def _fmt_duration_ms(ms: int) -> str:
    """'' for zero ms, 'Nm' under an hour, 'HhMm' for >= 1h."""
    if ms <= 0:
        return ''
    total_m = ms // 60_000
    h = total_m // 60
    m = total_m % 60
    if h == 0:
        return f'{m}m'
    return f'{h}h{m}m'


def _fmt_elapsed_clock(ms: int) -> str:
    """'' for <= 0 ms, MM:SS under an hour, H:MM:SS at or above."""
    if ms <= 0:
        return ''
    s   = ms // 1000
    h   = s // 3600
    m   = (s % 3600) // 60
    sec = s % 60
    if h == 0:
        return f'{m:02d}:{sec:02d}'
    return f'{h}:{m:02d}:{sec:02d}'


def _fmt_elapsed(mtime: float | None, now: float) -> str:
    """Seconds-since-mtime as a human-readable string; '' for None mtime."""
    if mtime is None:
        return ''
    return _fmt_duration_ms(int(max(0, now - mtime) * 1000))


# ---------------------------------------------------------------------------
# SessionView
# ---------------------------------------------------------------------------

class SessionView:
    def __init__(self, session: SessionInfo, cfg: Config, now: float | None = None, cache: TranscriptCache | None = None) -> None:
        self.session     = session
        self.cfg         = cfg
        self.now         = time.time() if now is None else now
        self.parse_cache = cache

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
            cache=self.parse_cache,
        )

    @cached_property
    def workflows(self) -> RunningWorkflows:
        return RunningWorkflows.from_session(
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
        return OpenSpec.from_cwd(self.session.cwd, max_depth=self.cfg.openspec_scan_depth).changes

    @cached_property
    def tool_counts(self) -> ToolCounts:
        """Per-tool (main, sub) tool_use counts since last /clear, plus session and per-agent line totals."""
        return ToolCounts.gather(
            self.session.transcript_path,
            self.subagents.subagents,
            self.clear_epoch,
            cache=self.parse_cache,
        )

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
        """Remaining cache TTL as (seconds_remaining, elapsed_pct); None if no anchor/expired/unknown TTL."""
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
    def clear_epoch(self) -> float | None:
        """Epoch of the most-recent /clear marker in this transcript, or None."""
        return read_clear_epoch(self.session.transcript_path)

    @cached_property
    def elapsed(self) -> str:
        return _fmt_elapsed_clock(self.session.cost.total_duration_ms)
