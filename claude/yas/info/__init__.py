"""SessionView — lazy gather seam for all derived session state.

All I/O is deferred to first access via @cached_property. Callers
construct a SessionView and read only the fields they need; unread
fields never touch the filesystem. SessionView may hold a loaded
transcript parse cache for deduplication but never writes it.
"""

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
from yas.guard import guarded


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
    """Format a duration in milliseconds as a clock string.

    Returns '' for zero or negative ms. Under an hour returns MM:SS (e.g.
    '13:27'); one hour or more returns H:MM:SS or HH:MM:SS (e.g. '1:13:27').
    """
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
    """Format seconds-since-mtime as a human-readable string.

    Kept as a wrapper around _fmt_duration_ms for backward-compatible callers.
    Returns '' for None mtime, 'Nm' for under an hour, 'HhMm' for >= 1 h.
    """
    if mtime is None:
        return ''
    return _fmt_duration_ms(int(max(0, now - mtime) * 1000))


def _no_changes() -> list[tuple[str, int, int]]:
    return []


def _no_epoch() -> float | None:
    return None


# ---------------------------------------------------------------------------
# SessionView
# ---------------------------------------------------------------------------

class SessionView:
    def __init__(self, session: SessionInfo, cfg: Config, now: float | None = None, cache: TranscriptCache | None = None, minimal: bool = False) -> None:
        self.session     = session
        self.cfg         = cfg
        self.now         = time.time() if now is None else now
        self.parse_cache = cache
        # Optional gathers that raised this render (names, for the marker), and
        # the retry mode that skips every optional gather (see yas.guard).
        self.failed: list[str] = []
        self.minimal           = minimal

    # ------------------------------------------------------------------
    # Leaf readers — each delegates to its existing classmethod
    # ------------------------------------------------------------------

    @guarded(GitInfo)
    def git(self) -> GitInfo:
        return GitInfo.from_cwd(self.session.cwd, status=self.cfg.show_git_status)

    @guarded(LoadedSkills)
    def skills(self) -> LoadedSkills:
        return LoadedSkills.from_transcript(self.session.transcript_path, cache=self.parse_cache)

    @guarded(RunningSubagents)
    def subagents(self) -> RunningSubagents:
        return RunningSubagents.from_session(
            self.session.session_id,
            self.session.workspace.project_dir,
            cache=self.parse_cache,
        )

    @guarded(RunningWorkflows)
    def workflows(self) -> RunningWorkflows:
        return RunningWorkflows.from_session(
            self.session.session_id,
            self.session.workspace.project_dir,
        )

    @guarded(TaskList)
    def tasks(self) -> TaskList:
        return TaskList.from_session(self.session.transcript_path, cache=self.parse_cache)

    @guarded(TranscriptUsage)
    def transcript_usage(self) -> TranscriptUsage:
        return TranscriptUsage.from_transcript(self.session.transcript_path, cache=self.parse_cache)

    @guarded(TranscriptUsage)
    def rate_limit_usage(self) -> TranscriptUsage:
        """Main + every subagent transcript's usage, for the rate-limit simulator only.

        Deliberately separate from `transcript_usage`: the cost row and other
        token displays stay main-thread-only (today's semantics), while the
        Bedrock-style 5h/7d bucket simulator needs the true session-wide burn
        -- a coordinator-heavy session can spend several times more tokens in
        subagents than on the main thread. See yas.info.transcript.
        TranscriptUsage.from_session.
        """
        return TranscriptUsage.from_session(
            self.session.transcript_path,
            cache=self.parse_cache,
            main_usage=self.transcript_usage,
        )

    @guarded(_no_changes)
    def changes(self) -> list[tuple[str, int, int]]:
        return OpenSpec.from_cwd(self.session.cwd, max_depth=self.cfg.openspec_scan_depth).changes

    @guarded(ToolCounts)
    def tool_counts(self) -> ToolCounts:
        """Per-tool (main, sub) tool_use counts, plus session and per-agent line totals.

        In a single pass through the main and all subagent transcripts, computes:
        - per-tool (main, sub) tool_use counts since the last /clear;
        - session totals for lines_read and lines_changed (sum of main + all subagents);
        - per_agent breakdown of lines_read and lines_changed for each subagent.

        Reopens the main transcript and each subagent transcript — no I/O beyond
        the files already scanned this render. A cached, unchanged transcript is
        not reopened at all. Lazy: a narrow/medium render that never reads this
        never pays for the aggregation.
        """
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

    @guarded(_no_epoch)
    def clear_epoch(self) -> float | None:
        """Epoch of the most-recent /clear marker in this transcript, or None.

        Holds no ANSI or render geometry; cached for the view's lifetime.
        """
        return read_clear_epoch(self.session.transcript_path)

    @cached_property
    def elapsed(self) -> str:
        return _fmt_elapsed_clock(self.session.cost.total_duration_ms)
