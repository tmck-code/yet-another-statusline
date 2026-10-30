"""SessionView — lazy gather seam for all derived session state.

All I/O is deferred to first access via @cached_property. Callers
construct a SessionView and read only the fields they need; unread
fields never touch the filesystem. SessionView may hold a loaded
transcript parse cache for deduplication but never writes it.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from functools import cached_property

from yas.config import Config
from yas.info.git import GitInfo
from yas.info.openspec import OpenSpec
from yas.session import SessionInfo
from yas.info.skills import LoadedSkills
from yas.info.shell_commands import (
    MAIN_AGENT_ID, AgentUsage, RunningShellCommands, main_inflight, split_by_owner,
)
from yas.info.main_activity import MainActivity, read_main_activity
from yas.info.subagents import RunningSubagents, _agent_is_live
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


@dataclass(frozen=True)
class ShellSplit:
    'Main-thread shell commands and the resource usage of each running subagent.'
    mine:       RunningShellCommands
    usage:      dict[str, AgentUsage]
    attributed: bool = True  # False when no process ownership was gathered


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
        return GitInfo.from_cwd(self.session.cwd, status=self.cfg.show_git_status)

    @cached_property
    def skills(self) -> LoadedSkills:
        return LoadedSkills.from_transcript(self.session.transcript_path, cache=self.parse_cache)

    @cached_property
    def _raw_subagents(self) -> RunningSubagents:
        return RunningSubagents.from_session(
            self.session.session_id,
            self.session.workspace.project_dir,
            cache=self.parse_cache,
        )

    @cached_property
    def subagents(self) -> RunningSubagents:
        # A running Bash tool call with no live process is a finished tool
        # whose result hasn't landed yet; show the agent as thinking, not as
        # still running its previous command. Only do that when ownership was
        # actually gathered: with resource usage or the shell section disabled
        # there is no process data, so the row keeps its Bash call.
        split = self._shell_split
        return self._raw_subagents.with_activity(
            self.now,
            split.usage,
            usage_attribution=split.attributed,
        )

    @cached_property
    def _shell_all(self) -> RunningShellCommands:
        if not self.cfg.shell_commands.enabled:
            return RunningShellCommands()
        # A live session always has a transcript on disk; without one (example
        # payloads, tests) the live process table must not be consulted.
        if not self.session.transcript_path or not os.path.isfile(self.session.transcript_path):
            return RunningShellCommands()
        return RunningShellCommands.from_session(
            self.session.session_id,
            self.session.transcript_path,
            self.cfg.shell_commands._replace(
                command_mode=self.cfg.shell_commands.effective_command_mode,
            ),
            cache=self.parse_cache,
        )

    @cached_property
    def _shell_split(self) -> ShellSplit:
        'Main-thread commands, and the resource usage of the processes each running subagent owns.'
        every = self._shell_all
        if not self.cfg.agents.resource_usage.enabled or not self.cfg.shell_commands.enabled:
            return ShellSplit(every, {}, attributed=False)
        if not every:
            return ShellSplit(every, {})
        owners = {s.agent_id: s.bash_inflight for s in self._raw_subagents.subagents
                  if s.status == 'running' and s.bash_inflight}
        if not owners:
            return ShellSplit(every, {})
        mine, theirs = split_by_owner(
            every.commands, owners,
            lambda: main_inflight(self.session.transcript_path, self.parse_cache), self.now,
        )
        return ShellSplit(RunningShellCommands(commands=mine), {o: AgentUsage.of(cs) for o, cs in theirs.items()})

    @cached_property
    def shell_commands(self) -> RunningShellCommands:
        'Shell commands of the main thread (those owned by a subagent show on its row instead).'
        return self._shell_split.mine

    @cached_property
    def subagent_usage(self) -> dict[str, AgentUsage]:
        """Resource usage per subagent: a running process, or a thinking timer.

        Thinking subagents get a zero-CPU/memory entry so the existing
        `[agents].resource_usage` columns also stay meaningful between tool
        calls, not only while a process is alive.
        """
        if not self.cfg.agents.resource_usage.enabled:
            return {}
        usage = dict(self._shell_split.usage)
        for sub in self.subagents.subagents:
            if sub.agent_id in usage or sub.status != 'running':
                continue
            kind = sub.last_activity[0]
            if kind == 'waiting':
                usage[sub.agent_id] = AgentUsage.waiting_for(self.now - sub.last_activity_ts)
                continue
            # `with_activity` has already rewritten a finished Bash call to
            # `thinking`; leave Read/Grep/text rows alone.
            if kind != 'thinking':
                continue
            thinking = self._thinking_usage(
                kind, sub.last_activity_ts, sub.mtime,
            )
            if thinking is not None:
                usage[sub.agent_id] = thinking
        return usage

    @cached_property
    def main_activity(self) -> MainActivity:
        'Last activity of the main transcript (for the synthetic main agent row).'
        return read_main_activity(self.session.transcript_path, cache=self.parse_cache)

    @cached_property
    def main_usage(self) -> AgentUsage | None:
        """Main-thread resource usage for the agents style.

        Running main-thread commands come first. With none, a live top-level
        subagent means main is waiting on it: zero CPU/memory plus a timer
        started when that child began. Otherwise a thinking transcript gets the
        thinking timer.
        """
        try:
            mine = self._shell_split.mine
        except (OSError, ValueError, KeyError, TypeError):
            # Shell gathering is best effort; a bad transcript or process
            # table must not remove the main row from the agents section.
            return None
        if mine:
            return AgentUsage.of(mine.commands)
        # An actively-thinking main thread is working, not waiting; only an
        # idle/finished turn is blocked on its children.
        if not self.main_activity.thinking:
            waiting_since = self._main_waiting_since()
            if waiting_since is not None:
                return AgentUsage.waiting_for(self.now - waiting_since)
        return self._thinking_usage(
            self.main_activity.kind, self.main_activity.since, self.main_activity.mtime,
        )

    def _main_waiting_since(self) -> float | None:
        'Start of the newest live top-level subagent, or None when main is not waiting on one.'
        subs = self.subagents.subagents
        ids = {s.agent_id for s in subs} | {s.agent_id.removeprefix('agent-') for s in subs}
        starts = [
            s.run_start_ts or s.first_timestamp
            for s in subs
            if (not s.parent_id or s.parent_id not in ids) and _agent_is_live(s)
        ]
        return max(starts) if starts else None

    @cached_property
    def agent_usage(self) -> dict[str, AgentUsage]:
        """Resource usage for the agents style: subagents plus the main session.

        A running subagent with no owned process but a thinking last activity
        gets a zero-CPU/memory entry whose elapsed time is the thinking timer.
        """
        usage = dict(self.subagent_usage)
        main = self.main_usage
        if main is not None:
            usage[MAIN_AGENT_ID] = main
        return usage

    def _thinking_usage(self, kind: str, since: float, mtime: float) -> AgentUsage | None:
        """A thinking AgentUsage, or None when the agent is not thinking or is stale.

        Only a recorded `thinking` block gets the timer, anchored at that
        block's first line. A running Bash call with no live process is
        rewritten to `thinking` by `with_activity` before this is called, so it
        still gets a timer; a `tool_use` / `text` / empty activity does not.
        """
        if kind != 'thinking' or since <= 0:
            return None
        if self.now - mtime > RunningSubagents.ABANDONED_HORIZON_SECONDS:
            return None
        return AgentUsage.thinking_for(self.now - since)

    @cached_property
    def workflows(self) -> RunningWorkflows:
        return RunningWorkflows.from_session(
            self.session.session_id,
            self.session.workspace.project_dir,
        )

    @cached_property
    def tasks(self) -> TaskList:
        return TaskList.from_session(self.session.transcript_path, cache=self.parse_cache)

    @cached_property
    def transcript_usage(self) -> TranscriptUsage:
        return TranscriptUsage.from_transcript(self.session.transcript_path, cache=self.parse_cache)

    @cached_property
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

    @cached_property
    def changes(self) -> list[tuple[str, int, int]]:
        return OpenSpec.from_cwd(self.session.cwd, max_depth=self.cfg.openspec_scan_depth).changes

    @cached_property
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

    @cached_property
    def clear_epoch(self) -> float | None:
        """Epoch of the most-recent /clear marker in this transcript, or None.

        Holds no ANSI or render geometry; cached for the view's lifetime.
        """
        return read_clear_epoch(self.session.transcript_path)

    @cached_property
    def elapsed(self) -> str:
        return _fmt_elapsed_clock(self.session.cost.total_duration_ms)
