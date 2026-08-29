"""Per-tool tool_use counting with a main-vs-sub split, plus lines read/changed.

Dedup keeps the LAST occurrence per message.id (opposite of transcript.py/subagents.py's
first-wins) since streamed writes to the same id can grow more tool_use blocks over time.

In-scope tools for line counts: Read, Write, Edit, and DesignSync's get_file method.
NotebookEdit and others are excluded.

Edit lines_changed = max(newlines(old_string), newlines(new_string)); Write = newlines(content).
replace_all:true counts once regardless of replacement count.

isSidechain:true records are skipped in the main transcript only, not subagent files —
some dispatch conventions tag every subagent record as sidechain, which would zero their
contribution if the skip applied there too. Safe because tool_use ids are disjoint between files.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from yas.constants import META_EXCLUDE_TOOLS
from yas.info.parsecache import TranscriptCache
from yas.info.subagents import RunningSubagent, _parse_iso_to_epoch

# cat -n style leading line number, any starting offset (Read(offset=N) numbers from N)
_CAT_N_PREFIX_RE = re.compile(r'^\d+\t')
# byte-level equivalent for the raw-line pre-filter (JSON-escaped tab is the 2 bytes \t)
_CAT_N_PREFIX_BYTES_RE = re.compile(rb'\d\\t')


@dataclass(slots=True)
class TranscriptToolStats:
    """Tool use and file-activity counts from one transcript walk."""

    counts: dict[str, int]  # tool name (MCP-normalized) -> count
    lines_read: int
    lines_changed: int


def count_transcript(
    path: str,
    clear_epoch: float | None,
    *,
    skip_sidechain: bool,
    cache: TranscriptCache | None = None,
    st: os.stat_result | None = None,
) -> TranscriptToolStats:
    """Count tool_use blocks and line activity in one transcript, at or after clear_epoch. Never raises."""
    if not path:
        return TranscriptToolStats(counts={}, lines_read=0, lines_changed=0)

    if cache is not None:
        try:
            st = st or os.stat(path)
        except OSError:
            st = None
        if st is not None:
            cached = cache.get_counts(path, st, clear_epoch, skip_sidechain)
            if cached is not None:
                cached_counts = cached['counts']
                cached_lines_read = cached['lines_read']
                cached_lines_changed = cached['lines_changed']
                if (
                    isinstance(cached_counts, dict)
                    and isinstance(cached_lines_read, int)
                    and isinstance(cached_lines_changed, int)
                ):
                    return TranscriptToolStats(
                        counts=cached_counts,
                        lines_read=cached_lines_read,
                        lines_changed=cached_lines_changed,
                    )

    def _nl(s: object) -> int:
        return s.count('\n') if isinstance(s, str) else 0

    per_id: dict[str, list[str]] = {}          # message.id -> tool names, most recent line wins
    per_id_changed: dict[str, int] = {}        # message.id -> total lines_changed
    read_ids: set[str] = set()                 # tool_use id -> seen Read, for matching tool_result
    designsync_read_ids: set[str] = set()      # tool_use id -> seen DesignSync get_file
    counted_read_ids: set[str] = set()         # tool_use_id already counted, guards duplicate tool_result
    lines_read = 0
    lines_changed = 0

    try:
        with open(path, 'rb') as fh:
            for raw in fh:
                # pre-filter before json.loads
                if b'"tool_use"' not in raw and b'"tool_result"' not in raw:
                    continue
                if b'"tool_result"' in raw and b'"tool_use"' not in raw:
                    if (
                        not _CAT_N_PREFIX_BYTES_RE.search(raw)
                        and b'get_file' not in raw
                    ):
                        continue
                if skip_sidechain:
                    if b'"isSidechain":true' in raw or b'"isSidechain": true' in raw:
                        continue

                try:
                    d = json.loads(raw)
                    msg = d.get('message') or {}

                    if clear_epoch is not None:
                        ts = d.get('timestamp', '') or ''
                        if _parse_iso_to_epoch(ts) < clear_epoch:
                            continue

                    # tool_result lives on a user-role message with no message.id, so this
                    # walk is unconditional; keyed on tool_use_id membership from the tool_use
                    # walk below (which always precedes it in the file).
                    for block in msg.get('content') or []:
                        if not isinstance(block, dict):
                            continue
                        if block.get('type') != 'tool_result':
                            continue
                        tool_use_id = block.get('tool_use_id')
                        if tool_use_id in counted_read_ids:
                            continue
                        content = block.get('content')
                        if tool_use_id in read_ids:
                            if isinstance(content, str) and _CAT_N_PREFIX_RE.match(
                                content
                            ):
                                lines_read += content.count('\n')
                            counted_read_ids.add(tool_use_id)
                        elif tool_use_id in designsync_read_ids:
                            # result is JSON {"method":"get_file",...,"content":...}, not a cat -n blob
                            if isinstance(content, str):
                                try:
                                    parsed = json.loads(content)
                                except (ValueError, TypeError):
                                    parsed = None
                                if isinstance(parsed, dict):
                                    file_text = parsed.get('content')
                                    if isinstance(file_text, str):
                                        lines_read += (
                                            file_text.count('\n') + 1
                                            if file_text
                                            else 0
                                        )
                            counted_read_ids.add(tool_use_id)

                    # The mid guard below only protects the tool_use-side
                    # accounting (`counts`, `lines_changed` via per_id /
                    # per_id_changed last-write-wins dedup) — tool_result
                    # records legitimately have no message.id and must not be
                    # gated by this check.
                    mid = msg.get('id')
                    if not mid:
                        continue

                    names: list[str] = []
                    id_changed = 0

                    # Walk tool_use blocks to record tool names and file activity.
                    for block in msg.get('content') or []:
                        if not isinstance(block, dict):
                            continue

                        if block.get('type') == 'tool_use':
                            name = block.get('name') or ''
                            if not name:
                                continue
                            name = name.split('__')[-1]  # MCP normalization
                            if name in META_EXCLUDE_TOOLS:
                                continue
                            names.append(name)

                            # Record file-activity per block (Decision 5).
                            if name == 'Read':
                                # Remember Read ids for tool_result pairing.
                                block_id = block.get('id')
                                if block_id:
                                    read_ids.add(block_id)
                            elif name == 'DesignSync':
                                # Only method 'get_file' is a read; other
                                # methods (e.g. list_files) are not.
                                inp = block.get('input') or {}
                                if inp.get('method') == 'get_file':
                                    block_id = block.get('id')
                                    if block_id:
                                        designsync_read_ids.add(block_id)
                            elif name == 'Edit':
                                # lines_changed += max(old_string, new_string)
                                inp = block.get('input') or {}
                                old = inp.get('old_string')
                                new = inp.get('new_string')
                                id_changed += max(_nl(old), _nl(new))
                            elif name == 'Write':
                                # lines_changed += content
                                inp = block.get('input') or {}
                                content = inp.get('content')
                                id_changed += _nl(content)
                            # Note: NotebookEdit is not counted (Decision 1).

                    # Last-write-wins dedup: replace per message.id and sum
                    # at the end (Decision 8).
                    per_id[mid] = names
                    per_id_changed[mid] = id_changed

                except (ValueError, TypeError):
                    continue
    except OSError:
        return TranscriptToolStats(counts={}, lines_read=0, lines_changed=0)

    # Sum tool counts and lines_changed across the final per-id state.
    counts: dict[str, int] = {}
    for names in per_id.values():
        for name in names:
            counts[name] = counts.get(name, 0) + 1
    lines_changed = sum(per_id_changed.values())

    result = TranscriptToolStats(
        counts=counts,
        lines_read=lines_read,
        lines_changed=lines_changed,
    )

    if cache is not None and st is not None:
        cache.put_counts(
            path, st, clear_epoch, skip_sidechain,
            {'counts': result.counts, 'lines_read': result.lines_read, 'lines_changed': result.lines_changed},
        )

    return result


class ToolCounts:
    """Per-tool ``(main, sub)`` tool_use counts, session line totals, and per-agent breakdown."""

    __slots__ = ('counts', 'lines_read', 'lines_changed', 'per_agent')

    def __init__(
        self,
        counts: dict[str, tuple[int, int]] | None = None,
        lines_read: int = 0,
        lines_changed: int = 0,
        per_agent: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        self.counts = counts if counts is not None else {}  # tool name -> (main_count, sub_count)
        self.lines_read = lines_read        # session total: main + all subagents
        self.lines_changed = lines_changed
        self.per_agent = per_agent if per_agent is not None else {}  # transcript path -> (lines_read, lines_changed)

    @property
    def total_types(self) -> int:
        """Number of distinct tool types counted (for +k overflow math)."""
        return len(self.counts)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ToolCounts):
            return NotImplemented
        return (
            self.counts == other.counts
            and self.lines_read == other.lines_read
            and self.lines_changed == other.lines_changed
            and self.per_agent == other.per_agent
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (
            f'ToolCounts('
            f'counts={self.counts!r}, '
            f'lines_read={self.lines_read}, '
            f'lines_changed={self.lines_changed}, '
            f'per_agent={self.per_agent!r})'
        )

    @classmethod
    def gather(
        cls,
        main_path:   str,
        subagents:   list[RunningSubagent],
        clear_epoch: float | None,
        cache: TranscriptCache | None = None,
    ) -> ToolCounts:
        """Build the merged (main, sub) counts, session line totals, and per-subagent line counts."""
        main_stats = count_transcript(
            main_path, clear_epoch, skip_sidechain=True, cache=cache
        )
        main_counts = main_stats.counts

        sub_counts: dict[str, int] = {}
        per_agent_lines: dict[str, tuple[int, int]] = {}
        total_lines_read = main_stats.lines_read
        total_lines_changed = main_stats.lines_changed

        for agent in subagents:
            agent_stats = count_transcript(
                agent.jsonl_path, clear_epoch, skip_sidechain=False, cache=cache
            )
            for name, n in agent_stats.counts.items():
                sub_counts[name] = sub_counts.get(name, 0) + n
            per_agent_lines[agent.jsonl_path] = (
                agent_stats.lines_read,
                agent_stats.lines_changed,
            )
            total_lines_read += agent_stats.lines_read
            total_lines_changed += agent_stats.lines_changed

        counts: dict[str, tuple[int, int]] = {}
        for name in main_counts.keys() | sub_counts.keys():
            counts[name] = (main_counts.get(name, 0), sub_counts.get(name, 0))

        return cls(
            counts=counts,
            lines_read=total_lines_read,
            lines_changed=total_lines_changed,
            per_agent=per_agent_lines,
        )
