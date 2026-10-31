"""Per-tool tool_use counting with a main-vs-sub split, plus lines read/changed.

Counts ``tool_use`` blocks per tool name across the main transcript and the
session's subagent transcripts, windowed to the last ``/clear`` and split into a
``main`` column (the session's own transcript) and a ``sub`` column (summed over
every subagent transcript). Also counts lines read and changed per transcript.

Dedup differs from the sibling readers on purpose. ``transcript.py`` and
``subagents.py`` keep the FIRST occurrence per ``message.id`` — correct for token
accounting, where usage is stable across the streamed writes and first-wins
avoids double-counting. Here we keep the LAST occurrence per ``message.id``:
``tool_use`` blocks carry no stable id of their own, and streaming writes the
same ``message.id`` several times where earlier partial writes may contain FEWER
``tool_use`` blocks than the final write. To count the true number of tool calls
we must count the content of the last write per id. Do NOT "fix" this to match
the sibling parsers — first-wins would undercount.

## In-scope tools

Line counts come from ``Read``, ``Write``, ``Edit``, ``MultiEdit``, ``Bash``
(read commands and heredoc file writes, see below), and the MCP ``DesignSync``
tool's ``get_file`` method (all other ``DesignSync`` methods, e.g.
``list_files``, are not reads). Others (``NotebookEdit``, etc.) are excluded.
``NotebookEdit`` is excluded because its cell model does not map cleanly to
line counts.

## Bash

Reads: split the command on ``&&``, ``||`` and ``;`` and take the last segment.
Its first pipeline command, ignoring leading ``VAR=x`` assignments and
``sudo``, is a read if its first word is ``cat``, ``head``, ``tail``, ``grep``,
``rg``, ``awk`` or ``nl``, or is ``sed`` with ``-n`` and without ``-i``. A
segment with an output redirect (``>``/``>>``) or ``tee`` is a write, not a
read. The newline count of the paired ``tool_result`` goes to ``lines_read``.

Writes: the body line count of each heredoc goes to ``lines_changed``, only
when the command redirects to a file (``>``, ``>>``, ``tee``). ``sed -i`` is
not counted. Unparseable commands (``shlex`` errors) count as nothing.

## Lines read measurement

For each ``Read`` ``tool_use``, ``lines_read`` accumulates the newline count of
the paired ``tool_result.content``, but only when that content is a string
whose first line starts with a numeric ``cat -n``-style prefix (one or more
digits followed by a tab). The numbering starts at the ``offset`` argument
when one is given, not necessarily at line 1 — ``Read(offset=500)`` yields
content beginning ``"500\t..."``, which still counts. Image and document
reads have list-valued content and are skipped. This is the canonical sniff
test for text-shaped reads.

For each ``DesignSync`` ``tool_use`` with ``input.method == 'get_file'``,
``lines_read`` accumulates the newline count of the ``.content`` field inside
the paired ``tool_result``, whose content is a JSON *string* shaped like
``{"method":"get_file","path":...,"content":"<file text>"}`` rather than a
``cat -n`` blob. If the result content doesn't parse as that shape (e.g. a
harness-truncated ``<persisted-output>`` wrapper), the entry is skipped, not
raised.

## Lines changed measurement

- ``Edit``: counted as ``max(newlines(old_string), newlines(new_string))``, the
  size of the touched hunk.
- ``MultiEdit``: the Edit rule applied to each entry of ``input.edits`` and summed.
- ``Write``: counted as ``newlines(content)``, the whole file written.

``replace_all: true`` is counted **once regardless of the number of replacements**,
so a bulk rename undercounts. This is accepted — the alternative requires
re-reading the edited file for every ``Edit``, which adds I/O cost.

## Main vs subagent sidechain asymmetry

Records with ``isSidechain: true`` in the **main** transcript are skipped;
``agent-*.jsonl`` files are counted in full with no sidechain filter. This is
deliberate: some dispatch conventions emit ``isSidechain: true`` for every
subagent record, so applying the skip to subagents would silently zero their
entire contribution, breaking the by-construction invariant
``session_total == main + Σ(subagents)``. The main-transcript skip alone suffices
because tool_use ids are fully disjoint between the two files.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass
from typing import Any, Callable

from yas.constants import META_EXCLUDE_TOOLS
from yas.info.parsecache import TranscriptCache, fold_file
from yas.info.subagents import RunningSubagent, _parse_iso_to_epoch

# Matches a cat -n style leading line number (any starting offset, not just
# line 1 — Read(offset=N) numbers its cat -n blob starting at N).
_CAT_N_PREFIX_RE = re.compile(r'^\d+\t')
# Byte-level equivalent of the above, for the pre-filter below (cheaper than
# json.loads; must not assume the numbering starts at 1). Matched against the
# raw JSON-encoded line, where a tab is escaped as the two-byte sequence
# b'\t' (backslash, t), not a literal tab byte.
_CAT_N_PREFIX_BYTES_RE = re.compile(rb'\d\\t')

# Bash classification. First words that read a file/stream to stdout.
_BASH_READ_WORDS = frozenset(('cat', 'head', 'tail', 'grep', 'rg', 'awk', 'nl'))
_BASH_SEPARATORS = frozenset(('&&', '||', ';'))
_BASH_REDIRECTS  = frozenset(('>', '>>', '&>', '&>>', '>|'))
_HEREDOC_RE      = re.compile(r'(?<!<)<<(?!<)-?\s*([\'"]?)([^\s\'"<>|&;()]+)\1')
_ASSIGNMENT_RE   = re.compile(r'^\w+=')


def _split_heredocs(cmd: str) -> tuple[str, int]:
    """Return ``(cmd without heredoc bodies, total heredoc body line count)``."""
    kept: list[str] = []
    delims: list[str] = []
    body_lines = 0
    for line in cmd.split('\n'):
        if delims:
            if line.strip() == delims[0]:
                delims.pop(0)
            else:
                body_lines += 1
            continue
        kept.append(line)
        delims = [m.group(2) for m in _HEREDOC_RE.finditer(line)]
    return '\n'.join(kept), body_lines


def _bash_segments(cmd: str) -> list[list[str]] | None:
    """Tokenize ``cmd`` and split on ``&&``/``||``/``;``; None on a parse error."""
    lexer = shlex.shlex(cmd.replace('\n', ' ; '), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok in _BASH_SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(tok)
    return [seg for seg in segments if seg]


def _writes_to_file(tokens: list[str]) -> bool:
    """True if ``tokens`` contain ``tee`` or a stdout redirect to a real file."""
    for i, tok in enumerate(tokens):
        if tok == 'tee':
            return True
        if tok not in _BASH_REDIRECTS:
            continue
        if i and tokens[i - 1] == '2':
            continue
        if i + 1 < len(tokens) and tokens[i + 1] == '/dev/null':
            continue
        return True
    return False


def _is_sed_read(args: list[str]) -> bool:
    """``sed`` with -n and without -i/--in-place."""
    has_n = False
    for arg in args:
        if arg == '--in-place' or arg.startswith('-i'):
            return False
        if re.fullmatch(r'-[A-Za-z]+', arg):
            if 'i' in arg:
                return False
            has_n = has_n or 'n' in arg
    return has_n


def _bash_is_read(segments: list[list[str]]) -> bool:
    """Classify the last segment's first pipeline command as a read."""
    if not segments:
        return False
    last = segments[-1]
    if _writes_to_file(last):
        return False
    pipeline = last[:last.index('|')] if '|' in last else last
    words = [t for t in pipeline if not _ASSIGNMENT_RE.match(t) and t != 'sudo']
    # Assignments/sudo only count as a prefix, but dropping them anywhere in
    # the first pipeline command is close enough for a line-count estimate.
    if not words:
        return False
    word = os.path.basename(words[0])
    if word == 'sed':
        return _is_sed_read(words[1:])
    return word in _BASH_READ_WORDS


def _classify_bash(cmd: object) -> tuple[bool, int]:
    """Return ``(is_read, heredoc_lines_written)`` for a Bash command string."""
    if not isinstance(cmd, str) or not cmd:
        return False, 0
    text, body_lines = _split_heredocs(cmd)
    segments = _bash_segments(text)
    if segments is None:
        return False, 0
    written = 0
    if body_lines and _writes_to_file([t for seg in segments for t in seg]):
        written = body_lines
    return _bash_is_read(segments), written


@dataclass(slots=True)
class TranscriptToolStats:
    """Tool use and file-activity counts from one transcript walk."""

    counts: dict[str, int]  # tool name (MCP-normalized) -> count
    lines_read: int
    lines_changed: int


def _nl(s: object) -> int:
    """Count newlines in a string, or 0 if not a string."""
    return s.count('\n') if isinstance(s, str) else 0


def _init_state() -> dict[str, Any]:
    """Fresh fold state. Id sets are dicts (id -> 1) so they survive JSON."""
    return {
        'per_id':              {},  # message.id -> tool names (last line wins)
        'per_id_changed':      {},  # message.id -> lines changed (last wins)
        'read_ids':            {},  # Read tool_use ids, for tool_result pairing
        'designsync_read_ids': {},  # DesignSync get_file tool_use ids
        'counted_read_ids':    {},  # ids whose tool_result already counted
        'bash_read_ids':       {},  # Bash read tool_use ids
        'bash_pending':        {},  # subset of bash_read_ids awaiting a result
        'lines_read':          0,
    }


def _make_fold(
    clear_epoch: float | None, skip_sidechain: bool,
) -> Callable[[dict[str, Any], list[bytes]], dict[str, Any]]:
    """Build the fold callable for one (clear_epoch, skip_sidechain) variant."""

    def fold(state: dict[str, Any], lines: list[bytes]) -> dict[str, Any]:
        per_id = state['per_id']
        per_id_changed = state['per_id_changed']
        read_ids = state['read_ids']
        designsync_read_ids = state['designsync_read_ids']
        counted_read_ids = state['counted_read_ids']
        bash_read_ids = state['bash_read_ids']
        bash_pending = state['bash_pending']
        lines_read = state['lines_read']
        # Bytes view of the pending ids for the cheap pre-filter below.
        pending_bytes = {k.encode() for k in bash_pending}

        for raw in lines:
            # Pre-filters: decide before json.loads.
            # (a) skip lines lacking both tool_use and tool_result
            if b'"tool_use"' not in raw and b'"tool_result"' not in raw:
                continue

            # (b) tool_result without tool_use needs a cat -n digit-tab marker
            #     (native Read, any start offset), the DesignSync get_file
            #     marker, or a pending Bash read id.
            if b'"tool_result"' in raw and b'"tool_use"' not in raw:
                if (
                    not _CAT_N_PREFIX_BYTES_RE.search(raw)
                    and b'get_file' not in raw
                    and not any(b in raw for b in pending_bytes)
                ):
                    continue

            # (c) reject sidechain records before decoding.
            if skip_sidechain:
                if b'"isSidechain":true' in raw or b'"isSidechain": true' in raw:
                    continue

            try:
                d = json.loads(raw)
                msg = d.get('message') or {}

                # Clear_epoch guard applies to every record.
                if clear_epoch is not None:
                    ts = d.get('timestamp', '') or ''
                    if _parse_iso_to_epoch(ts) < clear_epoch:
                        continue

                # tool_result blocks live on user-role lines that carry no
                # message.id, so this walk is independent of `mid`. Matching
                # uses the persisted id maps, so a result in a later chunk
                # than its tool_use still pairs.
                for block in msg.get('content') or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get('type') != 'tool_result':
                        continue
                    tool_use_id: Any = block.get('tool_use_id')
                    if tool_use_id in counted_read_ids:
                        continue
                    content = block.get('content')
                    if tool_use_id in read_ids:
                        if isinstance(content, str) and _CAT_N_PREFIX_RE.match(content):
                            lines_read += content.count('\n')
                        counted_read_ids[tool_use_id] = 1
                    elif tool_use_id in designsync_read_ids:
                        # JSON string {"method":"get_file",...,"content":...};
                        # skip on any shape mismatch (e.g. truncation wrapper).
                        if isinstance(content, str):
                            try:
                                parsed = json.loads(content)
                            except (ValueError, TypeError):
                                parsed = None
                            if isinstance(parsed, dict):
                                file_text = parsed.get('content')
                                if isinstance(file_text, str):
                                    lines_read += (
                                        file_text.count('\n') + 1 if file_text else 0
                                    )
                        counted_read_ids[tool_use_id] = 1
                    elif tool_use_id in bash_read_ids:
                        if isinstance(content, str):
                            lines_read += content.count('\n')
                        counted_read_ids[tool_use_id] = 1
                        bash_pending.pop(tool_use_id, None)
                        pending_bytes.discard(tool_use_id.encode())

                # The mid guard only protects tool_use-side accounting.
                mid = msg.get('id')
                if not mid:
                    continue

                names: list[str] = []
                id_changed = 0

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

                        if name == 'Read':
                            block_id = block.get('id')
                            if block_id:
                                read_ids[block_id] = 1
                        elif name == 'DesignSync':
                            inp = block.get('input') or {}
                            if inp.get('method') == 'get_file':
                                block_id = block.get('id')
                                if block_id:
                                    designsync_read_ids[block_id] = 1
                        elif name == 'Edit':
                            inp = block.get('input') or {}
                            id_changed += max(
                                _nl(inp.get('old_string')), _nl(inp.get('new_string'))
                            )
                        elif name == 'MultiEdit':
                            inp = block.get('input') or {}
                            for edit in inp.get('edits') or []:
                                if not isinstance(edit, dict):
                                    continue
                                id_changed += max(
                                    _nl(edit.get('old_string')),
                                    _nl(edit.get('new_string')),
                                )
                        elif name == 'Bash':
                            inp = block.get('input') or {}
                            is_read, written = _classify_bash(inp.get('command'))
                            id_changed += written
                            block_id = block.get('id')
                            if is_read and block_id:
                                bash_read_ids[block_id] = 1
                                if block_id not in counted_read_ids:
                                    bash_pending[block_id] = 1
                                    pending_bytes.add(block_id.encode())
                        elif name == 'Write':
                            inp = block.get('input') or {}
                            id_changed += _nl(inp.get('content'))
                        # NotebookEdit is not counted.

                # Last-write-wins per message.id, also across chunks.
                per_id[mid] = names
                per_id_changed[mid] = id_changed

            except (ValueError, TypeError):
                continue

        state['lines_read'] = lines_read
        return state

    return fold


def count_transcript(
    path: str,
    clear_epoch: float | None,
    *,
    skip_sidechain: bool,
    cache: TranscriptCache | None = None,
    st: os.stat_result | None = None,
) -> TranscriptToolStats:
    """Count tool_use blocks and line activity in one transcript file.

    Returns a ``TranscriptToolStats`` with tool counts, lines read, and lines
    changed for ``tool_use`` blocks at or after ``clear_epoch`` (whole file when
    ``clear_epoch`` is None), deduped by ``message.id`` keeping the LAST
    occurrence, meta-excluded, MCP-normalized.

    When ``skip_sidechain`` is True, records with ``isSidechain: true`` are
    skipped; when False, they are counted in full. This asymmetry is deliberate:
    see the module docstring.

    The walk is an incremental fold (``fold_file``): with a cache only bytes
    appended since the last call are parsed, and the persisted state carries
    every id map so the result equals a full parse.

    Never raises; an unreadable/malformed file yields empty counts and zeros.
    """
    empty = TranscriptToolStats(counts={}, lines_read=0, lines_changed=0)
    if not path:
        return empty
    try:
        st = st or os.stat(path)
    except OSError:
        return empty

    state = fold_file(
        cache, path, st, 'toolcounts', f'{clear_epoch!r}|{int(skip_sidechain)}',
        _init_state, _make_fold(clear_epoch, skip_sidechain),
    )

    counts: dict[str, int] = {}
    for names in state['per_id'].values():
        for name in names:
            counts[name] = counts.get(name, 0) + 1
    return TranscriptToolStats(
        counts=counts,
        lines_read=state['lines_read'],
        lines_changed=sum(state['per_id_changed'].values()),
    )


class ToolCounts:
    """Per-tool ``(main, sub)`` counts, session line totals, main's own share, and per-agent breakdown."""

    __slots__ = ('counts', 'lines_read', 'lines_changed', 'main_lines', 'per_agent')

    def __init__(
        self,
        counts: dict[str, tuple[int, int]] | None = None,
        lines_read: int = 0,
        lines_changed: int = 0,
        per_agent: dict[str, tuple[int, int]] | None = None,
        main_lines: tuple[int, int] | None = None,
    ) -> None:
        # tool name (MCP-normalized) -> (main_count, sub_count)
        self.counts = counts if counts is not None else {}
        # Session totals: main + all subagents.
        self.lines_read = lines_read
        self.lines_changed = lines_changed
        # Per-subagent breakdown: transcript path -> (lines_read, lines_changed)
        self.per_agent = per_agent if per_agent is not None else {}
        # Main transcript only; `per_agent` stays subagent-scoped.
        self.main_lines = main_lines if main_lines is not None else (0, 0)

    @property
    def total_types(self) -> int:
        """Number of distinct tool types counted (for +k overflow math)."""
        return len(self.counts)

    # Backwards-compatible alias.
    type_count = total_types

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ToolCounts):
            return NotImplemented
        return (
            self.counts == other.counts
            and self.lines_read == other.lines_read
            and self.lines_changed == other.lines_changed
            and self.main_lines == other.main_lines
            and self.per_agent == other.per_agent
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (
            f'ToolCounts('
            f'counts={self.counts!r}, '
            f'lines_read={self.lines_read}, '
            f'lines_changed={self.lines_changed}, '
            f'main_lines={self.main_lines!r}, '
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
        """Build the merged ``(main, sub)`` counts and session line totals.

        Also keeps main's own line counts (`main_lines`) apart from the
        per-subagent breakdown. The sidechain skip is asymmetric
        (main only, not subagents) — if applied to subagents, some dispatch
        conventions would zero the entire subagent contribution, breaking the
        by-construction invariant ``session_total == main + Σ(subagents)``.
        The id-disjointness verified in design.md Context makes this safe.
        """
        # Gather main transcript with sidechain skip (Decision 4).
        main_stats = count_transcript(
            main_path, clear_epoch, skip_sidechain=True, cache=cache
        )
        main_counts = main_stats.counts

        # Gather subagents with NO sidechain skip (Decision 4).
        sub_counts: dict[str, int] = {}
        per_agent_lines: dict[str, tuple[int, int]] = {}
        total_lines_read = main_stats.lines_read
        total_lines_changed = main_stats.lines_changed

        for agent in subagents:
            agent_stats = count_transcript(
                agent.jsonl_path, clear_epoch, skip_sidechain=False, cache=cache
            )
            # Accumulate tool counts across subagents.
            for name, n in agent_stats.counts.items():
                sub_counts[name] = sub_counts.get(name, 0) + n
            # Record per-subagent line counts and accumulate to session total.
            per_agent_lines[agent.jsonl_path] = (
                agent_stats.lines_read,
                agent_stats.lines_changed,
            )
            total_lines_read += agent_stats.lines_read
            total_lines_changed += agent_stats.lines_changed

        # Build the final (main, sub) tool counts.
        counts: dict[str, tuple[int, int]] = {}
        for name in main_counts.keys() | sub_counts.keys():
            counts[name] = (main_counts.get(name, 0), sub_counts.get(name, 0))

        return cls(
            counts=counts,
            lines_read=total_lines_read,
            lines_changed=total_lines_changed,
            per_agent=per_agent_lines,
            main_lines=(main_stats.lines_read, main_stats.lines_changed),
        )
