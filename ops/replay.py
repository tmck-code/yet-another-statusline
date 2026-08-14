#!/usr/bin/env python3
"""Session replay keyframe builder — read recordings, compute keyframes, write PSV output.

The replay system uses three layers:
1. Recording: gzip stream of ticks (ts | width | payload JSON) — compressed input
2. Keyframe PSV: one row per tick, full snapshot, pipe-separated plain text, with JSON blob columns
3. Playback: read PSV, parse blob columns as JSON, render via synth helpers

This module handles recording→keyframe transformation. The keyframes are
self-contained: after build, neither recording nor transcript is needed.
The output PSV is plain text (not compressed), human-inspectable, and greppable.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import tempfile
import time
import shutil
import signal
import subprocess
import termios
import tty
from argparse import Namespace
from pathlib import Path
from typing import Any
from datetime import datetime


# Inline sanitize to avoid circular imports: strips terminal control chars
_CTRL_RE = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]')


def _sanitize(s: str) -> str:
    """Strip terminal control characters from untrusted strings."""
    if not isinstance(s, str):
        return ''
    return _CTRL_RE.sub('', s)


# ==================== Arg parsing ====================


def parse_args(argv: list[str]) -> Namespace:
    """Parse CLI args for replay subcommands."""
    parser = argparse.ArgumentParser(
        description='Session replay keyframe builder',
    )
    subparsers = parser.add_subparsers(dest='cmd', required=True)

    # build subcommand
    build = subparsers.add_parser(
        'build',
        help='Build keyframes from recording and transcript',
    )
    build.add_argument(
        'session_id_or_path',
        metavar='SESSION_ID_OR_PATH',
        help='Session ID or path to .psv.gz recording',
    )
    build.add_argument(
        '-o',
        dest='output',
        metavar='PATH',
        default='replay.psv',
        help='Output file path (default: replay.psv)',
    )

    # play subcommand (reserve flags)
    play = subparsers.add_parser(
        'play',
        help='Playback a keyframe file',
    )
    play.add_argument(
        'keyframe_path',
        metavar='KEYFRAME_PATH',
        help='Path to .psv.gz keyframe file',
    )
    play.add_argument(
        '--speed',
        type=float,
        default=10.0,
        metavar='FACTOR',
        help='Playback speed factor (default: 10.0)',
    )
    play.add_argument(
        '--gap-cap',
        type=float,
        default=2.0,
        metavar='SECONDS',
        help='Max gap between ticks (default: 2.0)',
    )
    play.add_argument(
        '--width',
        default='recorded',
        metavar='MODE',
        help='Width mode: recorded/current/N (default: recorded)',
    )
    play.add_argument(
        '--no-hud',
        action='store_true',
        help='Disable HUD display',
    )

    # export subcommand (reserve flags)
    export = subparsers.add_parser(
        'export',
        help='Export keyframes to another format',
    )
    export.add_argument(
        'keyframe_path',
        metavar='KEYFRAME_PATH',
        help='Path to .psv.gz keyframe file',
    )
    export.add_argument(
        '-o',
        dest='output',
        metavar='PATH',
        help='Output file path',
    )
    export.add_argument(
        '--speed',
        type=float,
        default=10.0,
        metavar='FACTOR',
        help='Export speed factor (default: 10.0)',
    )
    export.add_argument(
        '--gap-cap',
        type=float,
        default=2.0,
        metavar='SECONDS',
        help='Max gap between ticks (default: 2.0)',
    )
    export.add_argument(
        '--width',
        default='recorded',
        metavar='MODE',
        help='Width mode: recorded/current/N (default: recorded)',
    )

    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Main entry point."""
    try:
        args = parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1

    if args.cmd == 'build':
        return build_keyframes(args)
    elif args.cmd == 'play':
        return play_keyframes(args)
    elif args.cmd == 'export':
        return export_keyframes(args)

    return 1


# ==================== Recording reader ====================


def read_recording(path: str) -> list[tuple[float, int, dict[str, Any]]]:
    """Read gzip recording, return list of (ts, width, payload).

    Malformed lines are skipped and counted. Returns successfully parsed ticks.
    """
    ticks: list[tuple[float, int, dict[str, Any]]] = []
    skipped = 0

    try:
        with gzip.open(path, 'rt', encoding='utf-8', errors='ignore') as fh:
            for line in fh:
                line = line.rstrip('\n')
                parts = line.split(' | ', 2)
                if len(parts) != 3:
                    skipped += 1
                    continue
                try:
                    ts = float(parts[0])
                    width = int(parts[1])
                    payload = json.loads(parts[2])
                    ticks.append((ts, width, payload))
                except (ValueError, json.JSONDecodeError):
                    skipped += 1
                    continue
    except OSError as e:
        print(f'Error reading recording: {e}', file=sys.stderr)
        return []

    if skipped > 0:
        print(f'Warning: skipped {skipped} malformed recording lines', file=sys.stderr)

    return ticks


# ==================== PSV format (reader, writer, payload derivation) ====================


def flatten_payload(payload: dict[str, Any], prefix: str = '') -> dict[str, str]:
    """Flatten nested payload to dotted leaf paths.

    Values are stringified; nested dicts are recursed; lists and non-leaf
    containers are skipped.
    """
    result: dict[str, str] = {}

    for key, val in payload.items():
        path = f'{prefix}{key}' if prefix else key
        if isinstance(val, dict):
            result.update(flatten_payload(val, f'{path}.'))
        elif isinstance(val, (list, tuple)):
            pass  # Skip lists/tuples
        else:
            # Leaf scalar value
            result[path] = str(val) if val is not None else ''

    return result


def derive_column_set(ticks: list[tuple[float, int, dict[str, Any]]]) -> set[str]:
    """Union all dotted leaf paths from all ticks' payloads."""
    columns = set()
    for _ts, _width, payload in ticks:
        columns.update(flatten_payload(payload).keys())
    return columns


def escape_blob_cell(s: str) -> str:
    """Escape pipes and backslashes in a blob cell for PSV format.

    Pipes in JSON blobs must be escaped to not break row splitting.
    Backslashes are escaped first to avoid double-escaping.
    """
    s = s.replace('\\', '\\\\')  # Backslash to double-backslash
    s = s.replace('|', '\\|')    # Pipe to backslash-pipe
    return s


def unescape_blob_cell(s: str) -> str:
    """Unescape pipes and backslashes in a blob cell from PSV format.

    Inverse of escape_blob_cell: undo in reverse order.
    """
    s = s.replace('\\|', '|')    # Backslash-pipe to pipe
    s = s.replace('\\\\', '\\')  # Double-backslash to backslash
    return s


def split_psv_row(line: str) -> list[str]:
    """Split a PSV row on pipes, respecting backslash escaping.

    Escaped pipes (\\|) are not treated as delimiters.
    Escaped backslashes (\\\\) are treated as literal backslashes.
    """
    cells = []
    current = []
    i = 0
    while i < len(line):
        if i < len(line) - 1 and line[i] == '\\' and line[i + 1] == '|':
            # Escaped pipe: include it and continue
            current.append('\\|')
            i += 2
        elif line[i] == '|':
            # Unescaped pipe: split here
            cells.append(''.join(current))
            current = []
            i += 1
        else:
            current.append(line[i])
            i += 1
    cells.append(''.join(current))
    return cells


def payload_to_psv_row(
    payload: dict[str, Any],
    columns: list[str],
) -> dict[str, str]:
    """Convert payload to dict of column -> cell value for PSV row."""
    flat = flatten_payload(payload)
    return {col: flat.get(col, '') for col in columns}


def _coerce_scalar(val: str) -> Any:
    """Coerce a PSV cell string back to the JSON type it originally was.

    PSV cells are always strings; a real payload sends proper JSON types
    (int/float/bool), and some consumers (e.g. ContextWindow.from_dict)
    require an actual numeric type rather than a numeric-looking string.
    """
    if val == 'True':
        return True
    if val == 'False':
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def psv_row_to_payload(row: dict[str, str], scalar_columns: set[str]) -> dict[str, Any]:
    """Rebuild payload from PSV row.

    Only scalar columns are rebuilt; blob columns are ignored.
    Missing/empty cells are omitted from the result (not stored as empty strings).
    """
    result: dict[str, Any] = {}

    for col, val in row.items():
        if col not in scalar_columns or not val:
            continue
        # Rebuild nested structure from dotted path
        parts = col.split('.')
        current = result
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = _coerce_scalar(val)

    return result


class PSVWriter:
    """Write keyframes to PSV format (pipe-separated values with JSON blobs)."""

    # Blob columns that contain JSON. Pipes in JSON strings must be escaped
    # to not break row splitting. When reading, we reconstruct these columns
    # by parsing JSON within the cell after unescaping pipes.
    BLOB_COLUMNS = {'tasks', 'subagents', 'tool_counts', 'rate_series'}

    def __init__(self, columns: list[str]):
        """Initialize with ordered column list (scalar + blob)."""
        self.columns = columns
        self.rows: list[dict[str, str]] = []

    def add_row(self, row: dict[str, str]) -> None:
        """Add a row (dict of col -> cell value)."""
        self.rows.append(row)

    def write(self, path: str) -> None:
        """Write rows as plain text PSV with header.

        The output file is plain text (not compressed), pipe-separated,
        with a header row naming every column. Pipes within blob values
        are escaped to preserve row structure.
        """
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.psv',
            delete=False,
            encoding='utf-8',
        ) as tmp:
            tmp_path = tmp.name
        try:
            with open(tmp_path, 'w', encoding='utf-8') as fh:
                # Header
                fh.write('|'.join(self.columns) + '\n')
                # Rows with blob escaping
                for row in self.rows:
                    cells = []
                    for col in self.columns:
                        val = row.get(col, '')
                        if col in self.BLOB_COLUMNS:
                            val = escape_blob_cell(val)
                        cells.append(val)
                    fh.write('|'.join(cells) + '\n')
            # Atomic rename
            os.rename(tmp_path, path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


class PSVReader:
    """Read keyframes from PSV format (plain text, pipe-separated)."""

    BLOB_COLUMNS = {'tasks', 'subagents', 'tool_counts', 'rate_series'}
    SCALAR_COLUMNS = {'ts', 'width', 'git_branch'}

    def __init__(self, path: str):
        """Open and read PSV file."""
        self.path = path
        self.columns: list[str] = []
        self.rows: list[dict[str, str]] = []
        self._read()

    def _read(self) -> None:
        """Read PSV from plain text file.

        Handles unescape of pipes in blob columns. Uses escape-aware
        splitting to preserve escaped pipes in blob values.
        """
        try:
            with open(self.path, 'r', encoding='utf-8') as fh:
                lines = fh.read().splitlines()
                if not lines:
                    return
                self.columns = split_psv_row(lines[0])
                for line in lines[1:]:
                    cells = split_psv_row(line)
                    row = {}
                    for i, col in enumerate(self.columns):
                        val = cells[i] if i < len(cells) else ''
                        if col in self.BLOB_COLUMNS:
                            val = unescape_blob_cell(val)
                        row[col] = val
                    self.rows.append(row)
        except OSError:
            pass

    def get_rows(self) -> list[dict[str, str]]:
        """Return list of row dicts."""
        return self.rows

    def row_to_payload(self, row: dict[str, str]) -> dict[str, Any]:
        """Rebuild payload from PSV row."""
        payload = psv_row_to_payload(row, set(row) - self.BLOB_COLUMNS)
        # Parse blob columns
        for col in self.BLOB_COLUMNS:
            if col in row and row[col]:
                try:
                    payload[col] = json.loads(row[col])
                except json.JSONDecodeError:
                    pass
        return payload


# ==================== Build command ====================


def _get_claude_dir() -> Path | None:
    """Get CLAUDE_DIR from environment or return None."""
    claude_dir = os.getenv('CLAUDE_DIR')
    if not claude_dir:
        return None
    return Path(claude_dir)


def _derive_slug(cwd: str) -> str:
    """Derive slug from cwd using same rule as write_subagents."""
    return re.sub(r'[^A-Za-z0-9]', '-', cwd)


def _resolve_recording_path(session_id_or_path: str, claude_dir: Path) -> str | None:
    """Resolve to recording path.

    If it looks like a path, use it directly. Otherwise treat as session ID
    and look in CLAUDE_DIR/yas/recordings/<session_id>.psv.gz.
    """
    if '/' in session_id_or_path or session_id_or_path.endswith('.psv.gz'):
        return session_id_or_path
    # Session ID: look in recordings dir
    recordings_dir = claude_dir / 'yas' / 'recordings'
    path = recordings_dir / f'{session_id_or_path}.psv.gz'
    return str(path)


def _read_transcript_envelope(path: str) -> list[dict[str, Any]]:
    """Read JSONL transcript file, return list of envelopes."""
    envelopes: list[dict[str, Any]] = []
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
            for line in fh:
                try:
                    envelopes.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return envelopes


def _read_task_creates_and_updates(envelopes: list[dict[str, Any]]) -> list[tuple[float, str, dict[str, Any]]]:
    """Extract TaskCreate/TaskUpdate records from transcript envelopes.

    Returns list of (ts, event_type, data) tuples.
    """
    events: list[tuple[float, str, dict[str, Any]]] = []

    for envelope in envelopes:
        ts_str = envelope.get('timestamp', '')
        try:
            if ts_str.endswith('Z'):
                ts_str = ts_str[:-1] + '+00:00'
            ts = datetime.fromisoformat(ts_str).timestamp()
        except (ValueError, TypeError):
            continue

        content = envelope.get('message', {}).get('content', [])
        if not isinstance(content, list):
            continue

        for c in content:
            if not isinstance(c, dict) or c.get('type') != 'tool_use':
                continue
            name = c.get('name', '')
            if name in ('TaskCreate', 'TaskUpdate'):
                events.append((ts, name, c.get('input', {})))

    return events


def _rebuild_tasks_at_tick(events: list[tuple[float, str, dict[str, Any]]], tick_ts: float) -> list[dict[str, Any]]:
    """Replay task events up to tick_ts, return list of task dicts."""
    by_id: dict[int, dict[str, Any]] = {}
    next_id = 1

    for event_ts, event_type, data in events:
        if event_ts > tick_ts:
            break
        if event_type == 'TaskCreate':
            # Reset on generation boundary
            if by_id and all(t.get('status') == 'completed' for t in by_id.values()):
                by_id = {}
                next_id = 1
            subj = _sanitize(data.get('subject', '') or '')
            af = _sanitize(data.get('activeForm', '') or '') or subj
            by_id[next_id] = {
                'id': next_id,
                'subject': subj,
                'active_form': af,
                'status': 'pending',
                'started_at': None,
                'completed_at': None,
            }
            next_id += 1
        elif event_type == 'TaskUpdate':
            try:
                tid = int(data.get('taskId', '0'))
            except (TypeError, ValueError):
                continue
            t = by_id.get(tid)
            if not t:
                continue
            new_status = data.get('status')
            if new_status in ('pending', 'in_progress', 'completed'):
                if new_status == 'in_progress':
                    t['started_at'] = event_ts
                    t['completed_at'] = None
                elif new_status == 'completed':
                    t['completed_at'] = event_ts
                t['status'] = new_status
            if 'activeForm' in data and data['activeForm']:
                t['active_form'] = _sanitize(data['activeForm'])
            if 'subject' in data and data['subject']:
                t['subject'] = _sanitize(data['subject'])

    return [by_id[k] for k in sorted(by_id.keys())]


def _get_git_branch_at_tick(envelopes: list[dict[str, Any]], tick_ts: float) -> str:
    """Get most recent gitBranch at or before tick_ts."""
    branch = ''
    for envelope in envelopes:
        ts_str = envelope.get('timestamp', '')
        try:
            if ts_str.endswith('Z'):
                ts_str = ts_str[:-1] + '+00:00'
            ts = datetime.fromisoformat(ts_str).timestamp()
        except (ValueError, TypeError):
            continue
        if ts <= tick_ts:
            branch = envelope.get('gitBranch', branch)
    return branch


def _derive_tool_counts_at_tick(envelopes: list[dict[str, Any]], tick_ts: float) -> dict[str, Any]:
    """Derive tool counts blob up to tick_ts.

    Counts tool uses per tool and line activity (Read/Write/Edit) up to tick_ts,
    windowed to the last `/clear` marker at or before the tick. When a `/clear`
    occurs at time c, only tool uses at or after c are counted for frames after c.

    Mirrors yas.info.toolcounts.py semantics: processes envelopes in order,
    counts tool_use blocks per tool, accumulates lines from tool results.

    Returns dict with:
    - counts: {tool_name: [main_count, sub_count], ...}
    - lines_read: total newlines from Read/DesignSync results
    - lines_changed: total touched lines from Edit/Write
    - per_agent: {agent_path: [lines_read, lines_changed], ...}
    """
    counts: dict[str, tuple[int, int]] = {}
    lines_read = 0
    lines_changed = 0

    # Regex for cat -n style line numbering (offset-aware)
    cat_n_re = re.compile(r'^\d+\t')

    # Track which Read/DesignSync calls we've seen for line counting
    read_ids: set[str] = set()
    counted_read_ids: set[str] = set()

    # Find the latest /clear marker at or before tick_ts
    last_clear_ts = 0.0
    for envelope in envelopes:
        ts_str = envelope.get('timestamp', '')
        try:
            if ts_str.endswith('Z'):
                ts_str = ts_str[:-1] + '+00:00'
            ts = datetime.fromisoformat(ts_str).timestamp()
        except (ValueError, TypeError):
            continue

        if ts > tick_ts:
            break

        msg = envelope.get('message', {})
        msg_text = msg.get('content', '')
        if isinstance(msg_text, str) and '/clear' in msg_text:
            last_clear_ts = ts

    for envelope in envelopes:
        # Parse timestamp and window to tick_ts
        ts_str = envelope.get('timestamp', '')
        try:
            if ts_str.endswith('Z'):
                ts_str = ts_str[:-1] + '+00:00'
            ts = datetime.fromisoformat(ts_str).timestamp()
        except (ValueError, TypeError):
            continue

        if ts > tick_ts:
            break

        # Skip tool uses before the last /clear marker
        if ts < last_clear_ts:
            continue

        msg = envelope.get('message', {})

        # Walk tool_result blocks to extract lines_read
        for block in msg.get('content', []):
            if not isinstance(block, dict):
                continue
            if block.get('type') != 'tool_result':
                continue
            tool_use_id = block.get('tool_use_id')
            if tool_use_id in counted_read_ids:
                continue
            content = block.get('content')
            if tool_use_id in read_ids:
                # Read tool result: cat -n format
                if isinstance(content, str) and cat_n_re.match(content):
                    lines_read += content.count('\n')
                counted_read_ids.add(tool_use_id)

        # Walk tool_use blocks to count and record lines_changed
        for block in msg.get('content', []):
            if not isinstance(block, dict):
                continue
            if block.get('type') != 'tool_use':
                continue

            name = block.get('name', '').split('__')[-1]
            if not name or name in ('TodoWrite', 'ExitPlanMode', 'AskUserQuestion'):
                continue

            if name not in counts:
                counts[name] = (0, 0)
            main_cnt, sub_cnt = counts[name]
            counts[name] = (main_cnt + 1, sub_cnt)

            # Track file activity
            if name == 'Read':
                block_id = block.get('id')
                if block_id:
                    read_ids.add(block_id)
            elif name == 'Edit':
                inp = block.get('input') or {}
                old = inp.get('old_string')
                new = inp.get('new_string')
                touched = max(
                    old.count('\n') if isinstance(old, str) else 0,
                    new.count('\n') if isinstance(new, str) else 0,
                )
                lines_changed += touched
            elif name == 'Write':
                inp = block.get('input') or {}
                content = inp.get('content')
                lines_changed += content.count('\n') if isinstance(content, str) else 0

    return {
        'counts': {name: list(pair) for name, pair in counts.items()},
        'lines_read': lines_read,
        'lines_changed': lines_changed,
        'per_agent': {},
    }


def _parse_iso_to_epoch(iso_str: str) -> float:
    """Parse ISO 8601 timestamp to epoch seconds."""
    try:
        if iso_str.endswith('Z'):
            iso_str = iso_str[:-1] + '+00:00'
        return datetime.fromisoformat(iso_str).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _read_subagent_usage_once(subagent_dir: str) -> dict[str, list[tuple[float, int]]]:
    """Read all agent-*.jsonl files once, return per-agent usage snapshots.

    Each agent-*.jsonl file is read exactly once. For each agent, this builds
    a list of (timestamp, cumulative_tokens) tuples. The cumulative_tokens at
    each timestamp represents the total tokens accumulated as of that point
    (considering the last-write-wins rule for each message ID).

    Returns dict[agent_id] -> list[(timestamp, cumulative_tokens)]
    sorted by timestamp. cumulative_tokens = sum of all message usages.
    """
    usage_by_agent: dict[str, list[tuple[float, int]]] = {}

    if not subagent_dir or not Path(subagent_dir).is_dir():
        return usage_by_agent

    try:
        for jsonl_path in sorted(Path(subagent_dir).glob('agent-*.jsonl')):
            agent_id = jsonl_path.stem.removeprefix('agent-')
            # Track message updates with timestamps
            usage_by_mid: dict[str, tuple[float, int]] = {}  # mid -> (ts, total_tokens)

            try:
                with open(jsonl_path, 'r', encoding='utf-8', errors='ignore') as fh:
                    for ln in fh:
                        # Skip lines without both usage and assistant markers
                        if '"usage"' not in ln or '"assistant"' not in ln:
                            continue

                        try:
                            d = json.loads(ln)
                        except (ValueError, TypeError):
                            continue

                        # Extract timestamp
                        ts_raw = d.get('timestamp', '')
                        ts = _parse_iso_to_epoch(ts_raw) if ts_raw else 0.0

                        msg = d.get('message') or {}
                        mid = msg.get('id')
                        if not mid or not ts:
                            continue

                        # Extract usage for this message
                        u = msg.get('usage') or {}
                        billed_in = (u.get('input_tokens', 0) or 0) + (u.get('cache_creation_input_tokens', 0) or 0)
                        cache_read_in = u.get('cache_read_input_tokens', 0) or 0
                        output = u.get('output_tokens', 0) or 0
                        total = billed_in + cache_read_in + output

                        # Store this message's usage (last-write-wins)
                        usage_by_mid[mid] = (ts, total)

            except Exception:
                continue

            # Now build cumulative snapshots from the collected records
            # Process all unique timestamps in order
            if usage_by_mid:
                # Collect all (timestamp, cumulative) pairs
                # For each distinct timestamp, compute the cumulative as of that time
                # (sum of all messages whose timestamp is <= that time)
                snapshots: list[tuple[float, int]] = []
                unique_timestamps = sorted(set(ts for ts, _ in usage_by_mid.values()))

                for snapshot_ts in unique_timestamps:
                    # Sum usage from all messages with timestamp <= snapshot_ts
                    cumulative = sum(
                        total for ts, total in usage_by_mid.values()
                        if ts <= snapshot_ts
                    )
                    snapshots.append((snapshot_ts, cumulative))

                usage_by_agent[agent_id] = snapshots

    except OSError:
        pass

    return usage_by_agent


def _derive_subagents_at_tick(
    subagent_dir: str,
    envelopes: list[dict[str, Any]],
    tick_ts: float,
    usage_by_agent: dict[str, list[tuple[float, int]]] | None = None,
    agent_meta_cache: dict[str, dict[str, Any]] | None = None,
    notif_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Derive subagents blob up to tick_ts.

    When called from build_keyframes (with usage_by_agent, agent_meta_cache, notif_map
    pre-loaded), uses those caches. When called standalone (for testing or replay),
    loads metadata and notifications on-the-fly.

    Returns list of dicts with: agent_type, description, parent_id, model,
    status, tokens (as int), last_activity (dict), spawn_depth, is_fork.
    """
    if not subagent_dir or not Path(subagent_dir).is_dir():
        return []

    # Load metadata cache if not provided (standalone call)
    if agent_meta_cache is None:
        agent_meta_cache = {}
        try:
            for meta_path in sorted(Path(subagent_dir).glob('*.meta.json')):
                try:
                    agent_id = meta_path.stem.removeprefix('agent-')
                    agent_meta_cache[agent_id] = json.loads(meta_path.read_text())
                except Exception:
                    continue
        except OSError:
            pass

    # Build notification map if not provided (standalone call)
    if notif_map is None:
        notif_map = {}
        for envelope in envelopes:
            ts_str = envelope.get('timestamp', '')
            try:
                ts = _parse_iso_to_epoch(ts_str)
            except Exception:
                continue

            if ts > tick_ts:
                break

            # Extract task notifications
            msg = envelope.get('message', {})
            msg_text = msg.get('content', '')
            if isinstance(msg_text, str) and '<task-notification>' in msg_text:
                for match in re.finditer(r'<task-id>(.*?)</task-id>', msg_text):
                    task_id = match.group(1).strip()
                    status_match = re.search(r'<status>(.*?)</status>', msg_text)
                    if status_match:
                        notif_map[task_id] = status_match.group(1).strip()

    subagents: list[dict[str, Any]] = []

    # Process each agent
    for agent_id, meta_data in agent_meta_cache.items():
        agent_type = _sanitize(meta_data.get('agentType', '') or '')
        description = _sanitize(meta_data.get('description', '') or '')
        parent_id = str(meta_data.get('parentAgentId', '') or '')
        model = str(meta_data.get('model', '') or '')
        spawn_depth = meta_data.get('spawnDepth', 0)
        is_fork = meta_data.get('isFork', False)

        # Status from notification (default to running)
        status = notif_map.get(agent_id, 'running')

        # Get usage data for this agent up to tick_ts
        tokens = 0
        last_activity: dict[str, Any] = {}
        if usage_by_agent and agent_id in usage_by_agent:
            # Find records at or before tick_ts
            for ts, total_tokens in usage_by_agent[agent_id]:
                if ts <= tick_ts:
                    tokens = total_tokens
                    last_activity = {'timestamp': ts}
                else:
                    break

        subagents.append({
            'agent_type': agent_type,
            'description': description,
            'parent_id': parent_id,
            'model': model,
            'status': status,
            'tokens': tokens,
            'last_activity': last_activity,
            'spawn_depth': spawn_depth,
            'is_fork': is_fork,
        })

    return subagents


def _derive_rate_series(ticks: list[tuple[float, int, dict[str, Any]]], idx: int) -> list[Any]:
    """Derive rate_series for keyframe at index idx.

    Computes tokens/second rate between consecutive keyframes from cumulative
    token totals. Returns empty list for first frame (no previous frame to diff).

    The rate is computed as: (current_tokens - prev_tokens) / (current_ts - prev_ts)
    where tokens = total billed input + cache read input + output tokens.

    Returns a list with one entry per rate sample (typically one sample per frame
    for adjacent frames).
    """
    if idx == 0:
        return []

    # Extract cumulative token totals from current and previous tick payloads
    curr_ts, _, curr_payload = ticks[idx]
    prev_ts, _, prev_payload = ticks[idx - 1]

    # Get token counts from payload; these are typically nested under 'session'
    def get_total_tokens(payload: dict[str, Any]) -> int:
        """Extract total tokens from payload, trying common field names."""
        # Try nested structure first (session.usage.total_tokens)
        session = payload.get('session', {})
        if isinstance(session, dict):
            usage = session.get('usage', {})
            if isinstance(usage, dict):
                total = usage.get('total_tokens')
                if isinstance(total, (int, float)):
                    return int(total)
        # Fallback to flat structure
        for key in ['total_tokens', 'cumulative_tokens', 'tokens']:
            val = payload.get(key)
            if isinstance(val, (int, float)):
                return int(val)
        return 0

    curr_tokens = get_total_tokens(curr_payload)
    prev_tokens = get_total_tokens(prev_payload)
    elapsed = curr_ts - prev_ts

    if elapsed <= 0:
        return []

    # Compute rate: tokens per second
    rate = (curr_tokens - prev_tokens) / elapsed if elapsed > 0 else 0.0

    return [{'rate': rate, 'elapsed': elapsed, 'tokens_delta': curr_tokens - prev_tokens}]


def build_keyframes(args: Namespace) -> int:
    """Build keyframes from recording and transcript."""
    claude_dir = _get_claude_dir()
    if not claude_dir:
        print('Error: CLAUDE_DIR not set', file=sys.stderr)
        return 1

    recording_path = _resolve_recording_path(args.session_id_or_path, claude_dir)
    if not recording_path or not Path(recording_path).is_file():
        print(f'Error: recording not found: {recording_path}', file=sys.stderr)
        return 1

    ticks = read_recording(recording_path)
    if not ticks:
        print(f'Error: no valid ticks in recording: {recording_path}', file=sys.stderr)
        return 1

    # Extract session ID and cwd from first tick's payload
    first_tick_payload = ticks[0][2] if ticks else {}
    transcript_path_hint = first_tick_payload.get('transcript_path', '')
    if not transcript_path_hint:
        print('Error: first tick missing transcript_path', file=sys.stderr)
        return 1

    # Derive session_id from transcript path
    # Expected format: CLAUDE_DIR/projects/<slug>/<session_id>.jsonl
    try:
        parts = Path(transcript_path_hint).parts
        session_id = Path(transcript_path_hint).stem  # filename without .jsonl
    except Exception:
        print(f'Error: cannot parse transcript_path: {transcript_path_hint}', file=sys.stderr)
        return 1

    # Resolve to absolute transcript path
    transcript_path = transcript_path_hint
    if not Path(transcript_path).is_absolute():
        transcript_path = str(claude_dir / 'projects' / Path(transcript_path_hint).name)

    if not Path(transcript_path).is_file():
        print(f'Error: transcript not found: {transcript_path}', file=sys.stderr)
        return 1

    # Read transcript
    envelopes = _read_transcript_envelope(transcript_path)
    if not envelopes:
        print(f'Error: no valid envelopes in transcript: {transcript_path}', file=sys.stderr)
        return 1

    # Derive columns from payloads
    scalar_columns = sorted(derive_column_set(ticks))
    all_columns = ['ts', 'width', 'git_branch'] + scalar_columns + ['tasks', 'subagents', 'tool_counts', 'rate_series']

    # Extract task events once
    task_events = _read_task_creates_and_updates(envelopes)

    # Resolve subagent directory
    # Derive slug from first tick's recorded cwd if available
    slug = _derive_slug(os.getcwd())
    subagent_dir = str(claude_dir / 'projects' / slug / session_id / 'subagents')

    # Read subagent usage and metadata once (single-pass rule)
    usage_by_agent = _read_subagent_usage_once(subagent_dir)

    # Pre-load agent metadata and notification map
    agent_meta_cache: dict[str, dict[str, Any]] = {}
    try:
        for meta_path in sorted(Path(subagent_dir).glob('*.meta.json')):
            try:
                agent_id = meta_path.stem.removeprefix('agent-')
                agent_meta_cache[agent_id] = json.loads(meta_path.read_text())
            except Exception:
                continue
    except OSError:
        pass

    # Pre-build notification map
    notif_map: dict[str, str] = {}
    for envelope in envelopes:
        ts_str = envelope.get('timestamp', '')
        try:
            ts = _parse_iso_to_epoch(ts_str)
        except Exception:
            continue

        # Extract task notifications
        msg = envelope.get('message', {})
        msg_text = msg.get('content', '')
        if isinstance(msg_text, str) and '<task-notification>' in msg_text:
            # Simple regex to extract task-id and status from notifications
            for match in re.finditer(r'<task-id>(.*?)</task-id>', msg_text):
                task_id = match.group(1).strip()
                status_match = re.search(r'<status>(.*?)</status>', msg_text)
                if status_match:
                    notif_map[task_id] = status_match.group(1).strip()

    # Build keyframes
    writer = PSVWriter(all_columns)
    sorted_ticks = sorted(ticks, key=lambda x: x[0])

    for i, (ts, width, payload) in enumerate(sorted_ticks):
        row: dict[str, str] = {}

        # Scalar columns
        row['ts'] = str(ts)
        row['width'] = str(width)
        row['git_branch'] = _get_git_branch_at_tick(envelopes, ts)

        # Payload scalars
        payload_row = payload_to_psv_row(payload, scalar_columns)
        row.update(payload_row)

        # Blob columns
        tasks = _rebuild_tasks_at_tick(task_events, ts)
        row['tasks'] = json.dumps(tasks, separators=(',', ':'), ensure_ascii=False)

        tool_counts = _derive_tool_counts_at_tick(envelopes, ts)
        row['tool_counts'] = json.dumps(tool_counts, separators=(',', ':'), ensure_ascii=False)

        subagents = _derive_subagents_at_tick(
            subagent_dir, envelopes, ts,
            usage_by_agent=usage_by_agent,
            agent_meta_cache=agent_meta_cache,
            notif_map=notif_map,
        )
        row['subagents'] = json.dumps(subagents, separators=(',', ':'), ensure_ascii=False)

        rate_series = _derive_rate_series(sorted_ticks, i)
        row['rate_series'] = json.dumps(rate_series, separators=(',', ':'), ensure_ascii=False)

        writer.add_row(row)

    # Write output atomically
    try:
        writer.write(args.output)
    except Exception as e:
        print(f'Error writing output: {e}', file=sys.stderr)
        return 1

    print(f'Wrote {len(ticks)} keyframes to {args.output}', file=sys.stderr)
    return 0


# ==================== Play helpers ====================


def _compute_frame_duration(gap: float, speed: float, gap_cap: float) -> float:
    """Compute wall-clock duration for a frame gap.

    Each gap is divided by speed, then capped at gap_cap.
    """
    return min(gap / speed, gap_cap)


def _resolve_seek_index(
    position: str,
    first_ts: float,
    last_ts: float,
    num_frames: int,
) -> int:
    """Map session-time position to frame index.

    Position can be:
    - ±10s, ±1min: relative offsets in seconds
    - 0-9: percentage jumps (N * 10%)
    Returns clamped index.
    """
    total_span = last_ts - first_ts
    if total_span <= 0:
        return 0

    try:
        # Try percentage jump (0-9)
        pct = int(position)
        if 0 <= pct <= 9:
            target_ts = first_ts + (pct / 10.0) * total_span
        else:
            # Try time offset
            offset_secs = float(position)
            target_ts = first_ts + offset_secs
    except ValueError:
        return 0

    # Find nearest frame by ts
    closest_idx = 0
    closest_dist = float('inf')
    # We don't have direct frame access here; this would need frames passed in
    # For now, return a placeholder that the caller will refine
    return closest_idx


def _resolve_width(recorded_width: int, terminal_width: int, mode: str) -> tuple[int, bool]:
    """Resolve render width and whether to warn about clamping.

    Returns (width, should_warn).
    - 'recorded': use recorded width, clamp to terminal if narrower
    - 'current': use terminal width (caller handles resize)
    - N: use fixed width N (no clamping)
    """
    if mode == 'recorded':
        if recorded_width > terminal_width:
            return (terminal_width, True)
        return (recorded_width, False)
    elif mode == 'current':
        return (terminal_width, False)
    else:
        try:
            return (int(mode), False)
        except ValueError:
            return (recorded_width, False)


def _format_hud(
    elapsed_secs: float,
    total_secs: float,
    speed: float,
    paused: bool,
    progress: float,
    width: int,
) -> str:
    """Format HUD line: `hh:mm:ss/hh:mm:ss [speed] [paused] [progress bar]`."""
    def _fmt_time(secs: float) -> str:
        """Format seconds as hh:mm:ss."""
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        s = int(secs % 60)
        return f'{h:02d}:{m:02d}:{s:02d}'

    elapsed_str = _fmt_time(elapsed_secs)
    total_str = _fmt_time(total_secs)
    speed_str = f'{speed:.1f}x'.rstrip('0').rstrip('.')
    paused_str = '[paused]' if paused else ''

    # Simple progress bar (10 chars)
    bar_len = 10
    filled = int(progress * bar_len)
    bar = '[' + '=' * filled + ' ' * (bar_len - filled) + ']'

    parts = [f'{elapsed_str}/{total_str}', speed_str]
    if paused_str:
        parts.append(paused_str)
    parts.append(bar)

    hud = ' '.join(parts)
    # Truncate if too long
    if len(hud) > width - 2:
        hud = hud[:width - 5] + '...'
    return hud


# ==================== Export helpers ====================


def _check_export_preflight() -> bool:
    """Check for ffmpeg and magick; return True if both present."""
    missing = []
    if not shutil.which('ffmpeg'):
        missing.append('ffmpeg')
    if not shutil.which('magick'):
        missing.append('magick')
    if missing:
        print(
            f'Error: missing required binaries: {", ".join(missing)}. '
            'Install ffmpeg and ImageMagick before exporting.',
            file=sys.stderr,
        )
        return False
    return True


def _validate_export_extension(path: str) -> bool:
    """Check if output extension is .mp4 or .gif."""
    ext = Path(path).suffix.lower()
    if ext not in ('.mp4', '.gif'):
        print(
            f'Error: unsupported output format {ext}. '
            'Supported formats: .mp4, .gif',
            file=sys.stderr,
        )
        return False
    return True


# ==================== Frame rendering ====================


def _render_frame(
    row: dict[str, str],
    tmpdir: Path,
    session_id: str,
    env: dict[str, str],
    width: int,
) -> str:
    """Render a single frame by invoking the statusline subprocess.

    Converts row blobs into synth writer vocabulary and returns ANSI output.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        import synth
    finally:
        if str(Path(__file__).parent) in sys.path:
            sys.path.pop(0)

    # Rebuild payload from row
    reader = PSVReader.__new__(PSVReader)
    reader.BLOB_COLUMNS = PSVReader.BLOB_COLUMNS
    reader.SCALAR_COLUMNS = PSVReader.SCALAR_COLUMNS
    payload = reader.row_to_payload(row)

    # Rate-limit resets_at is an absolute epoch checked against real wall-clock
    # `now` by the renderer. Rebase it onto real now so the recorded remaining
    # countdown (as of this row's ts) still reads correctly during replay.
    try:
        row_ts = float(row.get('ts', ''))
        now = time.time()
        for bucket in ('five_hour', 'seven_day'):
            resets_at = payload.get('rate_limits', {}).get(bucket, {}).get('resets_at')
            if resets_at:
                payload['rate_limits'][bucket]['resets_at'] = now + (resets_at - row_ts)
    except (ValueError, TypeError):
        pass

    # Extract blobs
    tasks_blob = row.get('tasks', '[]')
    subagents_blob = row.get('subagents', '[]')
    rate_series_blob = row.get('rate_series', '[]')
    tool_counts_blob = row.get('tool_counts', '{}')

    # Parse blobs
    try:
        tasks = json.loads(tasks_blob)
    except (json.JSONDecodeError, TypeError):
        tasks = []

    try:
        subagents = json.loads(subagents_blob)
    except (json.JSONDecodeError, TypeError):
        subagents = []

    try:
        rate_series = json.loads(rate_series_blob)
    except (json.JSONDecodeError, TypeError):
        rate_series = []

    # Convert tasks to synth.write_transcript format: list[tuple[str, str, str]]
    # Each task: (subject, active_form, status)
    task_tuples = [
        (t['subject'], t['active_form'], t['status'])
        for t in tasks
    ]

    # World is synthesized once by the caller before the per-frame loop begins.
    project_dir = tmpdir / 'my-project'

    # Pull this frame's actual usage out of the rebuilt payload so the
    # transcript we synthesize reflects the recording instead of staying at
    # zero for the life of the replay (SessionView derives tok/s, tool
    # counts, and day cost from the transcript file, not from the stdin
    # payload's context_window block).
    current_usage = payload.get('context_window', {}).get('current_usage', {}) \
        if isinstance(payload.get('context_window'), dict) else {}

    def _usage_int(key: str) -> int:
        try:
            return int(float(current_usage.get(key, 0)))
        except (TypeError, ValueError):
            return 0

    # Write transcript with tasks
    transcript_path = tmpdir / '.claude' / 'projects' / session_id / f'{session_id}.jsonl'
    synth.write_transcript(
        transcript_path,
        skills=[],
        total_in=_usage_int('input_tokens'),
        total_cc=_usage_int('cache_creation_input_tokens'),
        total_cr=_usage_int('cache_read_input_tokens'),
        total_out=_usage_int('output_tokens'),
        tasks=task_tuples if task_tuples else None,
    )

    # Write subagents
    # Convert subagents to synth.write_subagents format: list[tuple[...]]
    subagent_tuples = []
    for agent in subagents:
        # (agentType, description, billed_in, output_tokens)
        # Use tokens from blob if available (total of billed + cache_read + output)
        tokens = agent.get('tokens', 0)
        subagent_tuples.append((
            agent.get('agent_type', ''),
            agent.get('description', ''),
            tokens,  # billed_in (note: this is the full token total, not just billed)
            0,  # output_tokens (for compatibility, the tokens field is used instead)
        ))
    if subagent_tuples:
        synth.write_subagents(
            tmpdir / '.claude',
            session_id,
            project_dir,
            subagent_tuples,
        )

    # Write rate log (optional)
    if rate_series:
        rate_log_path = tmpdir / '.claude' / 'projects' / session_id / 'rate.log'
        try:
            # Write simple rate log
            lines = [f'{time.time():.3f} {session_id} 0 0']
            rate_log_path.write_text('\n'.join(lines) + '\n')
        except Exception:
            pass

    # Rewire paths
    synth.rewire_paths(payload, tmpdir, session_id)

    # Write git branch if needed
    git_branch = row.get('git_branch', 'main')
    if git_branch:
        project_git_dir = project_dir / '.git'
        if project_git_dir.is_dir():
            try:
                subprocess.run(
                    ['git', 'checkout', '-q', '-B', git_branch],
                    cwd=str(project_dir),
                    capture_output=True,
                )
            except Exception:
                pass

    # Render
    env_copy = env.copy()
    env_copy['COLUMNS'] = str(width)
    payload_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    return synth.render_once(env_copy, payload_json)


# ==================== Play command ====================


def play_keyframes(args: Namespace) -> int:
    """Play keyframes with interactive terminal UI."""
    # Read keyframes
    if not Path(args.keyframe_path).is_file():
        print(f'Error: keyframe file not found: {args.keyframe_path}', file=sys.stderr)
        return 1

    reader = PSVReader(args.keyframe_path)
    rows = reader.get_rows()
    if not rows:
        print('Error: no keyframes to play', file=sys.stderr)
        return 1

    # Extract timestamps and widths
    frame_ts = []
    frame_widths = []
    for row in rows:
        try:
            ts = float(row.get('ts', '0'))
            width = int(row.get('width', '80'))
            frame_ts.append(ts)
            frame_widths.append(width)
        except (ValueError, TypeError):
            pass

    if not frame_ts:
        print('Error: no valid timestamps in keyframes', file=sys.stderr)
        return 1

    first_ts = frame_ts[0]
    last_ts = frame_ts[-1]
    session_span = last_ts - first_ts

    # Resolve width
    terminal_size = shutil.get_terminal_size()
    terminal_width = terminal_size.columns
    recorded_width = frame_widths[0] if frame_widths else 80

    width_mode = args.width if hasattr(args, 'width') else 'recorded'
    render_width, should_warn = _resolve_width(recorded_width, terminal_width, width_mode)

    if should_warn and width_mode == 'recorded':
        print(
            f'Warning: terminal width {terminal_width} is narrower than '
            f'recorded width {recorded_width}; clamping to {render_width}',
            file=sys.stderr,
        )

    # Build hermetic world
    tmpdir = tempfile.TemporaryDirectory()
    try:
        tmpdir_path = Path(tmpdir.name)
        session_id = 'replay-session'

        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        try:
            import synth
        finally:
            if str(Path(__file__).parent) in _sys.path:
                _sys.path.pop(0)

        synth.build_synthetic_env(tmpdir_path, session_id)

        # Build child environment
        env = os.environ.copy()
        env['HOME'] = str(tmpdir_path)
        env['CLAUDE_CONFIG_DIR'] = str(tmpdir_path / '.claude')
        env.pop('TMUX_PANE', None)

        # State
        current_frame = 0
        paused = False
        speed = args.speed if hasattr(args, 'speed') else 10.0
        gap_cap = args.gap_cap if hasattr(args, 'gap_cap') else 2.0
        show_hud = not args.no_hud

        # Helper: render and display frame
        def render_and_display(frame_idx: int) -> str:
            """Render frame and return ANSI output."""
            if frame_idx < 0 or frame_idx >= len(rows):
                return ''
            row = rows[frame_idx]
            if width_mode == 'current':
                size = shutil.get_terminal_size()
                w = size.columns
            else:
                w = render_width
            return _render_frame(row, tmpdir_path, session_id, env, w)

        # Enter alternate screen and raw mode
        sys.stdout.write('\x1b[?1049h')
        sys.stdout.flush()

        # Get old terminal settings
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        try:
            # Set raw mode
            tty.setraw(fd)

            # Render first frame
            ansi_out = render_and_display(current_frame)
            sys.stdout.write('\x1b[H\x1b[J')
            sys.stdout.write(ansi_out.replace('\n', '\r\n'))
            if show_hud:
                elapsed = 0.0
                total = session_span
                progress = (frame_ts[current_frame] - first_ts) / session_span if session_span > 0 else 0
                hud = _format_hud(elapsed, total, speed, paused, progress, render_width)
                sys.stdout.write(f'\r\n{hud}\r\n')
            sys.stdout.flush()

            # Playback loop
            last_render_time = time.time()
            while True:
                if paused:
                    # Read key without timeout
                    try:
                        key = sys.stdin.read(1)
                    except KeyboardInterrupt:
                        break
                else:
                    # Calculate sleep time for next frame
                    if current_frame < len(rows) - 1:
                        gap = frame_ts[current_frame + 1] - frame_ts[current_frame]
                        frame_duration = _compute_frame_duration(gap, speed, gap_cap)
                    else:
                        frame_duration = 1.0

                    elapsed_since_render = time.time() - last_render_time
                    sleep_time = max(0, frame_duration - elapsed_since_render)

                    # Non-blocking read with timeout
                    import select
                    ready, _, _ = select.select([sys.stdin], [], [], sleep_time)
                    if ready:
                        key = sys.stdin.read(1)
                    else:
                        key = None

                if key:
                    # Handle keys
                    if key == ' ':
                        paused = not paused
                    elif key == 'q':
                        break
                    elif key in ('h', '\x1b'):  # left arrow or escape
                        # Check for escape sequence
                        if key == '\x1b':
                            next_ch = sys.stdin.read(1)
                            if next_ch == '[':
                                arrow_ch = sys.stdin.read(1)
                                if arrow_ch == 'D':  # Left
                                    current_frame = max(0, current_frame - 1)
                                    paused = True
                                elif arrow_ch == 'C':  # Right
                                    current_frame = min(len(rows) - 1, current_frame + 1)
                                    paused = True
                                elif arrow_ch == '5':  # PgUp
                                    # Next char is ~
                                    sys.stdin.read(1)
                                    current_frame = max(0, current_frame - 6)
                                    paused = True
                                elif arrow_ch == '6':  # PgDn
                                    sys.stdin.read(1)
                                    current_frame = min(len(rows) - 1, current_frame + 6)
                                    paused = True
                                elif arrow_ch == 'A':  # Up
                                    current_frame = max(0, current_frame - 6)
                                    paused = True
                                elif arrow_ch == 'B':  # Down
                                    current_frame = min(len(rows) - 1, current_frame + 6)
                                    paused = True
                    elif key == '+':
                        speed *= 2
                    elif key == '-':
                        speed = max(0.1, speed / 2)
                    elif key in '0123456789':
                        # Percentage jump
                        pct = int(key)
                        if session_span > 0:
                            target_ts = first_ts + (pct / 10.0) * session_span
                            # Find closest frame
                            closest_idx = 0
                            closest_dist = abs(frame_ts[0] - target_ts)
                            for i, ts in enumerate(frame_ts):
                                dist = abs(ts - target_ts)
                                if dist < closest_dist:
                                    closest_dist = dist
                                    closest_idx = i
                            current_frame = closest_idx
                            paused = True

                    # Redraw after key
                    if key in (' ', 'q', '+', '-') or key == '\x1b' or key in '0123456789':
                        ansi_out = render_and_display(current_frame)
                        sys.stdout.write('\x1b[?1049h')  # Re-enter alt screen
                        sys.stdout.write('\x1b[H\x1b[J')
                        sys.stdout.write(ansi_out.replace('\n', '\r\n'))
                        if show_hud:
                            elapsed = frame_ts[current_frame] - first_ts if current_frame < len(frame_ts) else 0
                            total = session_span
                            progress = elapsed / session_span if session_span > 0 else 0
                            hud = _format_hud(elapsed, total, speed, paused, progress, render_width)
                            sys.stdout.write(f'\r\n{hud}\r\n')
                        sys.stdout.flush()
                        last_render_time = time.time()

                # Advance frame if not paused and not at end
                if not paused and current_frame < len(rows) - 1:
                    # Render next frame
                    current_frame += 1
                    ansi_out = render_and_display(current_frame)
                    sys.stdout.write('\x1b[?1049h')
                    sys.stdout.write('\x1b[H\x1b[J')
                    sys.stdout.write(ansi_out.replace('\n', '\r\n'))
                    if show_hud:
                        elapsed = frame_ts[current_frame] - first_ts if current_frame < len(frame_ts) else 0
                        total = session_span
                        progress = elapsed / session_span if session_span > 0 else 0
                        hud = _format_hud(elapsed, total, speed, paused, progress, render_width)
                        sys.stdout.write(f'\r\n{hud}\r\n')
                    sys.stdout.flush()
                    last_render_time = time.time()

        except KeyboardInterrupt:
            pass
        finally:
            # Restore terminal
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            sys.stdout.write('\x1b[?1049l')
            sys.stdout.flush()

        return 0

    finally:
        tmpdir.cleanup()


# ==================== Export command ====================


def export_keyframes(args: Namespace) -> int:
    """Export keyframes to video or GIF."""
    # Preflight checks
    if not _check_export_preflight():
        return 1

    if not _validate_export_extension(args.output):
        return 1

    # Read keyframes
    if not Path(args.keyframe_path).is_file():
        print(f'Error: keyframe file not found: {args.keyframe_path}', file=sys.stderr)
        return 1

    reader = PSVReader(args.keyframe_path)
    rows = reader.get_rows()
    if not rows:
        print('Error: no keyframes to export', file=sys.stderr)
        return 1

    # Extract timestamps and widths
    frame_ts = []
    frame_widths = []
    for row in rows:
        try:
            ts = float(row.get('ts', '0'))
            width = int(row.get('width', '80'))
            frame_ts.append(ts)
            frame_widths.append(width)
        except (ValueError, TypeError):
            pass

    if not frame_ts:
        print('Error: no valid timestamps in keyframes', file=sys.stderr)
        return 1

    first_ts = frame_ts[0]
    last_ts = frame_ts[-1]

    # Resolve width
    width_mode = args.width if hasattr(args, 'width') else 'recorded'
    recorded_width = frame_widths[0] if frame_widths else 80
    terminal_width = shutil.get_terminal_size().columns
    render_width, _ = _resolve_width(recorded_width, terminal_width, width_mode)

    # Build hermetic world
    tmpdir = tempfile.TemporaryDirectory()
    png_tmpdir = tempfile.TemporaryDirectory()
    try:
        tmpdir_path = Path(tmpdir.name)
        png_dir = Path(png_tmpdir.name)
        session_id = 'replay-export'

        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        try:
            import synth
            import ansi_png
        finally:
            if str(Path(__file__).parent) in _sys.path:
                _sys.path.pop(0)

        synth.build_synthetic_env(tmpdir_path, session_id)

        # Build environment
        env = os.environ.copy()
        env['HOME'] = str(tmpdir_path)
        env['CLAUDE_CONFIG_DIR'] = str(tmpdir_path / '.claude')
        env.pop('TMUX_PANE', None)

        # First pass: render all frames and measure canvas
        speed = args.speed if hasattr(args, 'speed') else 10.0
        gap_cap = args.gap_cap if hasattr(args, 'gap_cap') else 2.0

        frame_pngs = []
        max_width = 0
        max_height = 0

        for frame_idx, row in enumerate(rows):
            # Render ANSI
            ansi_out = _render_frame(row, tmpdir_path, session_id, env, render_width)

            # Get PNG dimensions (first pass just to measure)
            png_path = png_dir / f'frame_{frame_idx:04d}.png'
            try:
                ansi_png.render_png_from_str(ansi_out, png_path)
                # Get image dimensions via identify
                try:
                    result = subprocess.run(
                        ['identify', '-format', '%w %h', str(png_path)],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    w, h = map(int, result.stdout.split())
                    max_width = max(max_width, w)
                    max_height = max(max_height, h)
                except subprocess.CalledProcessError:
                    pass

                frame_pngs.append((frame_idx, png_path))
            except Exception as e:
                print(f'Error rendering frame {frame_idx}: {e}', file=sys.stderr)
                return 1

        if not frame_pngs:
            print('Error: no frames rendered', file=sys.stderr)
            return 1

        # Second pass: render with fixed canvas
        canvas = (max_width, max_height) if (max_width > 0 and max_height > 0) else None
        frame_pngs_final = []

        for frame_idx, row in enumerate(rows):
            ansi_out = _render_frame(row, tmpdir_path, session_id, env, render_width)
            png_path = png_dir / f'frame_{frame_idx:04d}_final.png'
            try:
                ansi_png.render_png_from_str(ansi_out, png_path, canvas=canvas)
                frame_pngs_final.append((frame_idx, png_path))
            except Exception as e:
                print(f'Error rendering frame {frame_idx}: {e}', file=sys.stderr)
                return 1

        # Compute per-frame durations
        frame_durations = []
        for i in range(len(frame_ts)):
            if i < len(frame_ts) - 1:
                gap = frame_ts[i + 1] - frame_ts[i]
                duration = _compute_frame_duration(gap, speed, gap_cap)
            else:
                duration = 1.0
            frame_durations.append(duration)

        # Assemble video
        out_path = Path(args.output)
        out_ext = out_path.suffix.lower()

        if out_ext == '.mp4':
            # Create concat demuxer file
            concat_file = png_dir / 'concat.txt'
            concat_lines = []
            for (frame_idx, png_path), duration in zip(frame_pngs_final, frame_durations):
                concat_lines.append(f"file '{png_path}'")
                concat_lines.append(f'duration {duration}')
            concat_file.write_text('\n'.join(concat_lines) + '\n')

            # Run ffmpeg
            try:
                subprocess.run(
                    [
                        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                        '-i', str(concat_file),
                        '-pix_fmt', 'yuv420p',
                        '-c:v', 'libx264',
                        str(out_path),
                    ],
                    capture_output=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                print(f'Error assembling MP4: {e.stderr.decode()[:200]}', file=sys.stderr)
                return 1

        elif out_ext == '.gif':
            # Create palette
            palette_file = png_dir / 'palette.png'
            try:
                png_list = ','.join(str(p) for _, p in frame_pngs_final)
                subprocess.run(
                    [
                        'ffmpeg', '-y',
                        '-i', png_list,
                        '-vf', 'palettegen',
                        str(palette_file),
                    ],
                    capture_output=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                print(f'Error generating palette: {e.stderr.decode()[:200]}', file=sys.stderr)
                return 1

            # Create GIF with palette
            try:
                concat_file = png_dir / 'concat_gif.txt'
                concat_lines = []
                for (frame_idx, png_path), duration in zip(frame_pngs_final, frame_durations):
                    concat_lines.append(f"file '{png_path}'")
                    concat_lines.append(f'duration {duration}')
                concat_file.write_text('\n'.join(concat_lines) + '\n')

                subprocess.run(
                    [
                        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                        '-i', str(concat_file),
                        '-i', str(palette_file),
                        '-filter_complex', 'paletteuse',
                        str(out_path),
                    ],
                    capture_output=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                print(f'Error assembling GIF: {e.stderr.decode()[:200]}', file=sys.stderr)
                return 1

        print(f'Exported {len(frame_pngs_final)} frames to {out_path}', file=sys.stderr)
        return 0

    finally:
        tmpdir.cleanup()
        png_tmpdir.cleanup()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
