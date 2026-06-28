"""Per-tool tool_use counting with a main-vs-sub split.

Counts ``tool_use`` blocks per tool name across the main transcript and the
session's subagent transcripts, windowed to the last ``/clear`` and split into a
``main`` column (the session's own transcript) and a ``sub`` column (summed over
every subagent transcript).

Dedup differs from the sibling readers on purpose. ``transcript.py`` and
``subagents.py`` keep the FIRST occurrence per ``message.id`` — correct for token
accounting, where usage is stable across the streamed writes and first-wins
avoids double-counting. Here we keep the LAST occurrence per ``message.id``:
``tool_use`` blocks carry no stable id of their own, and streaming writes the
same ``message.id`` several times where earlier partial writes may contain FEWER
``tool_use`` blocks than the final write. To count the true number of tool calls
we must count the content of the last write per id. Do NOT "fix" this to match
the sibling parsers — first-wins would undercount.
"""

from __future__ import annotations

import json

from yas.constants import META_EXCLUDE_TOOLS
from yas.info.subagents import RunningSubagent, _parse_iso_to_epoch


def count_transcript(path: str, clear_epoch: float | None) -> dict[str, int]:
    """Count tool_use blocks per tool name in one transcript file.

    Returns ``{tool_name: count}`` for ``tool_use`` blocks at or after
    ``clear_epoch`` (whole file when ``clear_epoch`` is None), deduped by
    ``message.id`` keeping the LAST occurrence, meta-excluded, MCP-normalized.
    Never raises; an unreadable/malformed file yields ``{}``.
    """
    if not path:
        return {}
    # message.id -> tool names from the most recent line seen for that id.
    per_id: dict[str, list[str]] = {}
    try:
        with open(path, errors='ignore') as fh:
            for ln in fh:
                if '"tool_use"' not in ln:
                    continue
                try:
                    d   = json.loads(ln)
                    msg = d.get('message') or {}
                    mid = msg.get('id')
                    if not mid:
                        continue
                    if clear_epoch is not None:
                        ts = d.get('timestamp', '') or ''
                        if _parse_iso_to_epoch(ts) < clear_epoch:
                            continue
                    names: list[str] = []
                    for block in (msg.get('content') or []):
                        if not isinstance(block, dict) or block.get('type') != 'tool_use':
                            continue
                        name = block.get('name') or ''
                        if not name:
                            continue
                        name = name.split('__')[-1]  # MCP mcp__server__tool -> tool
                        if name in META_EXCLUDE_TOOLS:
                            continue
                        names.append(name)
                    per_id[mid] = names  # last write wins
                except (ValueError, TypeError):
                    continue
    except OSError:
        return {}
    counts: dict[str, int] = {}
    for names in per_id.values():
        for name in names:
            counts[name] = counts.get(name, 0) + 1
    return counts


class ToolCounts:
    """Per-tool ``(main, sub)`` tool_use counts plus the distinct-type total."""

    __slots__ = ('counts',)

    def __init__(self, counts: dict[str, tuple[int, int]] | None = None) -> None:
        # tool name (MCP-normalized) -> (main_count, sub_count)
        self.counts = counts if counts is not None else {}

    @property
    def total_types(self) -> int:
        """Number of distinct tool types counted (for +k overflow math)."""
        return len(self.counts)

    # Backwards-compatible alias.
    type_count = total_types

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ToolCounts):
            return NotImplemented
        return self.counts == other.counts

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'ToolCounts(counts={self.counts!r})'

    @classmethod
    def gather(
        cls,
        main_path:   str,
        subagents:   list[RunningSubagent],
        clear_epoch: float | None,
    ) -> ToolCounts:
        """Build the merged ``(main, sub)`` counts from the main transcript and cohort."""
        main = count_transcript(main_path, clear_epoch)
        sub: dict[str, int] = {}
        for agent in subagents:
            for name, n in count_transcript(agent.jsonl_path, clear_epoch).items():
                sub[name] = sub.get(name, 0) + n
        counts: dict[str, tuple[int, int]] = {}
        for name in main.keys() | sub.keys():
            counts[name] = (main.get(name, 0), sub.get(name, 0))
        return cls(counts=counts)
