"""RunningSubagent and RunningSubagents — active sub-agent discovery.

Per-render transcript parsers and tail-cache readers. Module-level tail caches
(_notif_tail_cache, _tool_result_tail_cache) hold process-local state; an
optional yas.info.parsecache.TranscriptCache persists tail offsets/findings
across process restarts so a fresh render doesn't rescan whole transcripts."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from yas.constants import _sanitize, last_prompt_path, projects_dir, subagent_is_terminal, subagent_status

if TYPE_CHECKING:
    from yas.info.parsecache import TranscriptCache


def read_last_prompt_ts(session_id: str) -> float | None:
    '''Last UserPromptSubmit timestamp for session_id from last-prompt.json, or None. Never raises.'''
    try:
        state = last_prompt_path()
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


# Bias rule: an unrecognised/missing status is never treated as done.
_TERMINAL_STATUSES = frozenset(('completed', 'killed', 'failed', 'stopped'))

_TASK_NOTIF_RE      = re.compile(r'<task-notification>(.*?)</task-notification>', re.DOTALL)
_TASK_ID_TAG_RE      = re.compile(r'<task-id>(.*?)</task-id>', re.DOTALL)
_TOOL_USE_ID_TAG_RE  = re.compile(r'<tool-use-id>(.*?)</tool-use-id>', re.DOTALL)
_STATUS_TAG_RE       = re.compile(r'<status>(.*?)</status>', re.DOTALL)

class _TailCacheEntry(NamedTuple):
    '''One cached tail-read state: (mtime, size, byte-offset consumed, notifications found).'''
    mtime:         float
    size:          int
    offset:        int
    notifications: list['_Notification']


# Tail-read cache keyed by absolute path: unchanged (mtime, size) skips I/O;
# a changed file is only read from the last consumed offset onward.
_notif_tail_cache: dict[str, _TailCacheEntry] = {}


class _Notification:
    '''One parsed <task-notification> occurrence.'''
    __slots__ = ('task_id', 'tool_use_id', 'status', 'ts')

    def __init__(self, task_id: str, tool_use_id: str, status: str, ts: float) -> None:
        self.task_id     = task_id
        self.tool_use_id = tool_use_id
        self.status      = status
        self.ts          = ts


def _extract_notifications(line: str) -> list[_Notification]:
    '''Extract zero or more <task-notification> blocks from one JSONL line.
    Handles queue-operation and user record shapes, falling back to a raw
    substring scan so no notification is silently dropped.'''
    out: list[_Notification] = []
    text_blob: str | None = None
    ts = 0.0
    try:
        d = json.loads(line)
    except (ValueError, TypeError):
        d = None
    if isinstance(d, dict):
        ts_raw = d.get('timestamp', '')
        if ts_raw:
            ts = _parse_iso_to_epoch(str(ts_raw))
        rtype = d.get('type')
        if rtype == 'queue-operation':
            content = d.get('content')
            if isinstance(content, str):
                text_blob = content
        elif rtype == 'user':
            msg_raw = d.get('message')
            msg = msg_raw if isinstance(msg_raw, dict) else {}
            content = msg.get('content')
            if isinstance(content, str):
                text_blob = content
    if text_blob is None and '<task-notification>' in line:
        text_blob = line
    if text_blob is None or '<task-notification>' not in text_blob:
        return out
    for block in _TASK_NOTIF_RE.findall(text_blob):
        tid_m    = _TASK_ID_TAG_RE.search(block)
        tool_m   = _TOOL_USE_ID_TAG_RE.search(block)
        status_m = _STATUS_TAG_RE.search(block)
        task_id     = tid_m.group(1).strip()    if tid_m    else ''
        tool_use_id = tool_m.group(1).strip()   if tool_m   else ''
        status      = status_m.group(1).strip() if status_m else ''
        if task_id:
            out.append(_Notification(task_id, tool_use_id, status, ts))
    return out


def _tail_read_notifications(path: Path, cache: TranscriptCache | None = None) -> list[_Notification]:
    '''Read new <task-notification> records since path was last seen, tailing from
    the cached byte offset; offset only advances to a complete line boundary so a
    mid-write line is re-read whole next time. Never raises. cache enables
    cross-process warm-start.'''
    key = str(path)
    # Seed the module-level cache from persistent storage if available.
    if cache is not None and key not in _notif_tail_cache:
        cached_state = cache.get_notif(key)
        if cached_state is not None:
            mtime, size, offset, items = cached_state
            _notif_tail_cache[key] = _TailCacheEntry(mtime, size, offset, items)

    try:
        st = path.stat()
    except OSError:
        cached = _notif_tail_cache.get(key)
        return cached.notifications if cached else []

    cached = _notif_tail_cache.get(key)
    if cached is not None and cached.mtime == st.st_mtime and cached.size == st.st_size:
        return cached.notifications

    # A shrunk (rotated/truncated) file can't be tailed sanely — rescan from 0.
    reusable    = cached is not None and cached.size <= st.st_size
    prev_offset = cached.offset if reusable and cached is not None else 0
    notifications = list(cached.notifications) if reusable and cached is not None else []

    try:
        with path.open('rb') as fh:
            fh.seek(prev_offset)
            chunk = fh.read()
    except OSError:
        _notif_tail_cache[key] = _TailCacheEntry(st.st_mtime, st.st_size, prev_offset, notifications)
        if cache is not None:
            cache.put_notif(key, st.st_mtime, st.st_size, prev_offset, notifications)
        return notifications

    last_nl = chunk.rfind(b'\n')
    if last_nl == -1:
        # No complete line yet; store prev_offset (not new_offset) so the
        # still-growing partial line is re-read whole next time.
        _notif_tail_cache[key] = _TailCacheEntry(st.st_mtime, st.st_size, prev_offset, notifications)
        if cache is not None:
            cache.put_notif(key, st.st_mtime, st.st_size, prev_offset, notifications)
        return notifications

    new_offset = prev_offset + last_nl + 1
    for raw_line in chunk[:last_nl].split(b'\n'):
        if b'<task-notification>' not in raw_line:
            continue
        notifications.extend(_extract_notifications(raw_line.decode('utf-8', errors='ignore')))

    _notif_tail_cache[key] = _TailCacheEntry(st.st_mtime, st.st_size, new_offset, notifications)
    if cache is not None:
        cache.put_notif(key, st.st_mtime, st.st_size, new_offset, notifications)
    return notifications


class _ToolResultCacheEntry(NamedTuple):
    '''One cached tail-read state for toolUseResult scanning: (mtime, size,
    byte-offset consumed, tool_use_id -> (status, ts) map found so far).'''
    mtime:   float
    size:    int
    offset:  int
    results: dict[str, tuple[str, float]]


# Tail-read cache for toolUseResult scanning, keyed by absolute path string.
_tool_result_tail_cache: dict[str, _ToolResultCacheEntry] = {}


def _extract_tool_results(line: str) -> list[tuple[str, str, float]]:
    '''Extract zero or more (tool_use_id, status, ts) triples from one JSONL line:
    a top-level ``toolUseResult`` field (sibling of ``message``) on a ``type:
    "user"`` record, matched against its ``message.content`` tool_result block.
    Written by Claude Code core for every resolved Agent/Task call, independent
    of whether a <task-notification> was ever emitted.'''
    out: list[tuple[str, str, float]] = []
    try:
        d = json.loads(line)
    except (ValueError, TypeError):
        return out
    if not isinstance(d, dict) or d.get('type') != 'user':
        return out
    tur = d.get('toolUseResult')
    if not isinstance(tur, dict):
        return out
    status = tur.get('status')
    if not isinstance(status, str) or not status:
        return out
    msg = d.get('message')
    content = msg.get('content') if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return out
    ts_raw = d.get('timestamp') or tur.get('timestamp') or ''
    ts = _parse_iso_to_epoch(str(ts_raw)) if ts_raw else 0.0
    for item in content:
        if isinstance(item, dict) and item.get('type') == 'tool_result':
            tool_use_id = str(item.get('tool_use_id', '') or '')
            if tool_use_id:
                out.append((tool_use_id, status, ts))
    return out


def _tail_read_tool_results(path: Path, cache: TranscriptCache | None = None) -> dict[str, tuple[str, float]]:
    '''Read new tool_use_id -> (status, ts) pairs from path's toolUseResult sibling
    fields, tailing like _tail_read_notifications. cache enables cross-process warm-start.'''
    key = str(path)
    # Seed the module-level cache from persistent storage if available.
    if cache is not None and key not in _tool_result_tail_cache:
        cached_state = cache.get_tool_results(key)
        if cached_state is not None:
            mtime, size, offset, results = cached_state
            _tool_result_tail_cache[key] = _ToolResultCacheEntry(mtime, size, offset, results)

    try:
        st = path.stat()
    except OSError:
        cached = _tool_result_tail_cache.get(key)
        return cached.results if cached else {}

    cached = _tool_result_tail_cache.get(key)
    if cached is not None and cached.mtime == st.st_mtime and cached.size == st.st_size:
        return cached.results

    reusable    = cached is not None and cached.size <= st.st_size
    prev_offset = cached.offset if reusable and cached is not None else 0
    results     = dict(cached.results) if reusable and cached is not None else {}

    try:
        with path.open('rb') as fh:
            fh.seek(prev_offset)
            chunk = fh.read()
    except OSError:
        _tool_result_tail_cache[key] = _ToolResultCacheEntry(st.st_mtime, st.st_size, prev_offset, results)
        if cache is not None:
            cache.put_tool_results(key, st.st_mtime, st.st_size, prev_offset, results)
        return results

    last_nl = chunk.rfind(b'\n')
    if last_nl == -1:
        # No complete line yet; store prev_offset (not new_offset) so the
        # still-growing partial line is re-read whole next time.
        _tool_result_tail_cache[key] = _ToolResultCacheEntry(st.st_mtime, st.st_size, prev_offset, results)
        if cache is not None:
            cache.put_tool_results(key, st.st_mtime, st.st_size, prev_offset, results)
        return results

    new_offset = prev_offset + last_nl + 1
    for raw_line in chunk[:last_nl].split(b'\n'):
        if b'"toolUseResult"' not in raw_line:
            continue
        for tool_use_id, status, ts in _extract_tool_results(raw_line.decode('utf-8', errors='ignore')):
            results[tool_use_id] = (status, ts)

    _tool_result_tail_cache[key] = _ToolResultCacheEntry(st.st_mtime, st.st_size, new_offset, results)
    if cache is not None:
        cache.put_tool_results(key, st.st_mtime, st.st_size, new_offset, results)
    return results


# Every logical <task-notification> is written TWICE (~20-25ms apart: a
# "queue-operation" then a "user" record) for the same task-id. Undeduped,
# run_count double-counts, which can collapse a resumed agent's duration to
# ~0:00. Window: comfortably above the twin gap, below any real distinct-run gap.
NOTIF_DEDUPE_WINDOW_SECONDS = 1.0


def _dedupe_notifications(notes: list['_Notification']) -> list['_Notification']:
    '''Collapse same-task-id notifications within NOTIF_DEDUPE_WINDOW_SECONDS into
    one, keeping the LATER twin (the "user" record). Output is ts-ascending.'''
    if len(notes) <= 1:
        return list(notes)
    ordered = sorted(notes, key=lambda n: n.ts)
    deduped = [ordered[0]]
    for note in ordered[1:]:
        if note.ts - deduped[-1].ts <= NOTIF_DEDUPE_WINDOW_SECONDS:
            deduped[-1] = note
        else:
            deduped.append(note)
    return deduped


class _NotifLookup(NamedTuple):
    '''Aggregated notification state for one task-id: latest status/ts, the
    PREVIOUS notification's ts (0.0 if none), and total occurrence count.
    prev_ts brackets a finished-and-resumed run's start (see from_session) —
    anchoring on the last notification alone would collapse duration to ~0.'''
    status:       str
    ts:           float
    prev_ts:      float
    notif_count:  int


def _collect_task_notifications(
    session_jsonl: Path, subagents_dir: Path, cache: TranscriptCache | None = None
) -> dict[str, _NotifLookup]:
    '''Build a ``{task_id: _NotifLookup(status, ts, prev_ts, count)}`` map for one
    session tree, scanning the top-level session .jsonl AND every
    subagents/agent-*.jsonl (a nested agent's notification lands in its PARENT's
    transcript). Notifications are deduped per task-id first; latest occurrence
    decides status/ts, second-latest gives prev_ts, count is the deduped run count.'''
    by_task: dict[str, list[_Notification]] = {}

    def _absorb(path: Path) -> None:
        for note in _tail_read_notifications(path, cache=cache):
            if note.task_id:
                by_task.setdefault(note.task_id, []).append(note)

    if session_jsonl.is_file():
        _absorb(session_jsonl)
    if subagents_dir.is_dir():
        try:
            for jsonl in subagents_dir.glob('agent-*.jsonl'):
                _absorb(jsonl)
        except OSError:
            pass

    result: dict[str, _NotifLookup] = {}
    for task_id, notes in by_task.items():
        by_ts   = _dedupe_notifications(notes)
        latest  = by_ts[-1]
        prev_ts = by_ts[-2].ts if len(by_ts) >= 2 else 0.0
        result[task_id] = _NotifLookup(
            status=latest.status, ts=latest.ts, prev_ts=prev_ts, notif_count=len(by_ts),
        )
    return result


def parse_transcript(
    jsonl: Path,
    resume_after: float = 0.0,
    *,
    cache: TranscriptCache | None = None,
    st: os.stat_result | None = None,
    totals_only: bool = False,
) -> tuple[int, int, int, float, str, tuple[str, str, dict[str, object]], float, float]:
    """Parse one agent-*.jsonl transcript into the subagent metric tuple
    ``(billed_in, cache_read_in, output, first_ts, model, last_activity, end_ts,
    run_start_ts)``. Module-level so info/workflows.py shares the same logic.

    ``resume_after``, when positive, is the resume-boundary timestamp (the
    last-seen <task-notification> before the run being displayed); the
    returned ``run_start_ts`` is the first line postdating it, found in the
    same streaming pass. 0.0 when resume_after is 0.0 or no later line exists.
    Never raises; an unreadable transcript yields zeroes.

    When cache is set and totals_only is False, loads/stores a parse result
    keyed by (path, resume_after). totals_only results are NEVER cached (blanked
    fields would poison a later full-fidelity read).

    totals_only skips model/activity resolution (model='', last_activity=('',
    '', {})); all other fields must equal the full-parse value. Pre-filters
    input in binary for speed on large transcripts, but always decodes the
    FIRST and LAST complete lines so first_ts/run_start_ts/end_ts stay exact.
    """
    # Try to load from cache if available and not totals_only.
    if cache is not None and not totals_only:
        if st is None:
            try:
                st = jsonl.stat()
            except OSError:
                st = None
        if st is not None:
            cached = cache.get_parse(str(jsonl), st, resume_after)
            if cached is not None:
                return cached

    if totals_only:
        seen: set[str] = set()
        usage_by_id: dict[str, tuple[int, int, int]] = {}
        first_ts     = 0.0
        run_start_ts = 0.0
        end_ts       = 0.0
        model        = ''
        last_activity: tuple[str, str, dict[str, object]] = ('', '', {})

        try:
            with jsonl.open('rb') as fh:
                content = fh.read()
        except OSError:
            result: tuple[int, int, int, float, str, tuple[str, str, dict[str, object]], float, float] = (
                0, 0, 0, 0.0, '', ('', '', {}), 0.0, 0.0,
            )
            # Never cache a totals_only result (it has blanked fields).
            return result

        lines = content.split(b'\n')
        if not lines:
            result = (0, 0, 0, 0.0, '', ('', '', {}), 0.0, 0.0)
            return result

        need_run_start = resume_after > 0.0

        if lines:
            first_line = lines[0]
            if first_line:
                try:
                    d = json.loads(first_line.decode('utf-8', errors='ignore'))
                    ts_raw = d.get('timestamp', '')
                    if ts_raw:
                        first_ts = _parse_iso_to_epoch(ts_raw)
                except (ValueError, TypeError):
                    pass

        for i, raw_line in enumerate(lines):
            if not raw_line:
                continue

            if need_run_start and b'"timestamp"' in raw_line:
                try:
                    d = json.loads(raw_line.decode('utf-8', errors='ignore'))
                    ts_raw = d.get('timestamp', '')
                    if ts_raw:
                        parsed = _parse_iso_to_epoch(ts_raw)
                        if parsed > resume_after:
                            run_start_ts = parsed
                            need_run_start = False
                except (ValueError, TypeError):
                    pass

            # Pre-filter: only decode usage lines.
            if b'"usage"' not in raw_line or b'"assistant"' not in raw_line:
                continue

            try:
                d = json.loads(raw_line.decode('utf-8', errors='ignore'))
            except (ValueError, TypeError):
                continue

            msg = d.get('message') or {}
            mid = msg.get('id')

            # Capture end_ts from end_turn (last-write-wins).
            try:
                stop   = msg.get('stop_reason')
                ts_raw = d.get('timestamp', '')
                line_ts = _parse_iso_to_epoch(ts_raw) if ts_raw else 0.0
                if stop == 'end_turn' and line_ts:
                    end_ts = line_ts
                elif stop != 'end_turn':
                    end_ts = 0.0
            except (ValueError, TypeError, AttributeError):
                pass

            if not mid:
                continue

            # Capture usage (last-line-wins).
            u = msg.get('usage') or {}
            usage_by_id[mid] = (
                (u.get('input_tokens', 0) or 0) + (u.get('cache_creation_input_tokens', 0) or 0),
                u.get('cache_read_input_tokens', 0) or 0,
                u.get('output_tokens', 0) or 0,
            )

        billed_in     = sum(billed for billed, _, _ in usage_by_id.values())
        cache_read_in = sum(cached for _, cached, _ in usage_by_id.values())
        output        = sum(out for _, _, out in usage_by_id.values())

        result = (billed_in, cache_read_in, output, first_ts, model, last_activity, end_ts, run_start_ts)
        return result

    # Full parse mode (not totals_only).
    seen = set()
    # Usage keyed by message id, last-line-wins: streaming re-writes the same id
    # as content grows, and the final write carries the real totals.
    usage_by_id = {}
    first_ts     = 0.0
    run_start_ts = 0.0
    end_ts       = 0.0
    model        = ''
    last_activity = ('', '', {})
    # Activity accumulates across a message id's streamed writes (resets on id
    # change) so later tool_use/text blocks are seen, not just the first (thinking).
    cur_mid  = ''
    cur_tool: dict[str, object] | None = None
    cur_text: dict[str, object] | None = None
    cur_has_content = False
    try:
        with jsonl.open('r', errors='ignore') as fh:
            for ln in fh:
                need_run_start = resume_after > 0.0 and run_start_ts == 0.0
                if ('"timestamp"' in ln) and (first_ts == 0.0 or need_run_start):
                    try:
                        d = json.loads(ln)
                        ts_raw = d.get('timestamp', '')
                        if ts_raw:
                            parsed = _parse_iso_to_epoch(ts_raw)
                            if first_ts == 0.0:
                                first_ts = parsed
                            if need_run_start and parsed > resume_after:
                                run_start_ts = parsed
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
                # Terminal check runs on every line (not behind mid dedup): last-write-
                # wins so a later non-terminal write clears a stale end_ts (a subagent
                # can be resumed after end_turn). Kept for direct callers (workflows.py);
                # RunningSubagent.end_ts is always overwritten from the notification map.
                try:
                    stop   = msg.get('stop_reason')
                    ts_raw = d.get('timestamp', '')
                    line_ts = _parse_iso_to_epoch(ts_raw) if ts_raw else 0.0
                    if stop == 'end_turn' and line_ts:
                        end_ts = line_ts
                    elif stop != 'end_turn':
                        end_ts = 0.0
                except (ValueError, TypeError, AttributeError):
                    pass
                if not mid:
                    continue
                u = msg.get('usage') or {}
                usage_by_id[mid] = (
                    (u.get('input_tokens', 0) or 0) + (u.get('cache_creation_input_tokens', 0) or 0),
                    u.get('cache_read_input_tokens', 0) or 0,
                    u.get('output_tokens', 0) or 0,
                )
                if mid != cur_mid:
                    cur_mid  = mid
                    cur_tool = None
                    cur_text = None
                    cur_has_content = False
                for item in (msg.get('content') or []):
                    if not isinstance(item, dict):
                        continue
                    cur_has_content = True
                    kind = item.get('type', '')
                    if kind == 'tool_use':
                        cur_tool = item
                    elif kind == 'text':
                        cur_text = item
                if mid in seen:
                    continue
                seen.add(mid)
                if not model:
                    m = msg.get('model') or ''
                    if m:
                        model = m
    except OSError:
        pass
    billed_in     = sum(billed for billed, _, _ in usage_by_id.values())
    cache_read_in = sum(cached for _, cached, _ in usage_by_id.values())
    output        = sum(out for _, _, out in usage_by_id.values())
    # Activity reflects the final message: last tool_use wins over trailing text
    # narration, then the first non-empty line of the last text block, then thinking.
    if cur_tool is not None:
        raw_inp = cur_tool.get('input') or {}
        inp = {
            k: _sanitize(v) if isinstance(v, str) else v
            for k, v in raw_inp.items()
        } if isinstance(raw_inp, dict) else {}
        last_activity = ('tool_use', _sanitize(str(cur_tool.get('name', '') or '')), inp)
    elif cur_text is not None:
        snippet = ''
        for line in str(cur_text.get('text', '') or '').splitlines():
            stripped = line.strip()
            if stripped:
                snippet = _sanitize(stripped)
                break
        last_activity = ('text', snippet, {})
    elif cur_has_content:
        last_activity = ('thinking', '', {})
    # end_ts here is end_turn-only (a real API field); no prose/heuristic completion
    # is inferred. RunningSubagent.end_ts is always overwritten from the
    # <task-notification> map in RunningSubagents.from_session instead.

    result = (billed_in, cache_read_in, output, first_ts, model, last_activity, end_ts, run_start_ts)

    # Store in cache if available and not totals_only.
    if cache is not None:
        if st is None:
            try:
                st = jsonl.stat()
            except OSError:
                st = None
        if st is not None:
            cache.put_parse(str(jsonl), st, resume_after, result)

    return result


def _build_tree_index(
    subs: list[RunningSubagent],
) -> tuple[dict[int, list[RunningSubagent]], list[RunningSubagent]]:
    '''Build the parent→children map and root list shared by the tree helpers.
    Matches ``sub.parent_id`` against a sibling's ``agent_id`` (with/without the
    ``agent-`` prefix); unmatched parent -> root. Returns (children keyed by
    id(parent), roots).'''
    by_id: dict[str, RunningSubagent] = {}
    for sub in subs:
        if sub.agent_id:
            by_id[sub.agent_id] = sub
            by_id[sub.agent_id.removeprefix('agent-')] = sub
    children: dict[int, list[RunningSubagent]] = {}
    roots: list[RunningSubagent] = []
    for sub in subs:
        parent = by_id.get(sub.parent_id) if sub.parent_id else None
        if parent is not None and parent is not sub:
            children.setdefault(id(parent), []).append(sub)
        else:
            roots.append(sub)
    return children, roots


def tree_order(subs: list[RunningSubagent]) -> list[tuple[RunningSubagent, int, bool]]:
    '''Order a visible cohort parent-first: (sub, depth, is_last_child) triples,
    depth-first, siblings in first_timestamp order. Pure ordering — no ANSI, no glyphs.'''
    children, roots = _build_tree_index(subs)
    out: list[tuple[RunningSubagent, int, bool]] = []

    def walk(sub: RunningSubagent, depth: int, last: bool) -> None:
        out.append((sub, depth, last))
        kids = children.get(id(sub), [])
        for i, kid in enumerate(kids):
            walk(kid, depth + 1, i == len(kids) - 1)

    for root in roots:
        walk(root, 0, False)
    return out


def _subtree_has_active(sub: RunningSubagent, children: dict[int, list[RunningSubagent]]) -> bool:
    '''True if ``sub`` or any transitive descendant is still running.
    Drives tree-connector colour (white vs grey).'''
    if not subagent_is_terminal(subagent_status(sub)):
        return True
    return any(_subtree_has_active(kid, children) for kid in children.get(id(sub), []))


def tree_order_full(
    subs: list[RunningSubagent],
) -> list[tuple[RunningSubagent, int, bool, bool, tuple[bool, ...], tuple[bool, ...], bool]]:
    '''Like ``tree_order``, plus box-drawing prefix shape info: whether the node
    has children, and per-ancestor-level whether the vertical connector should
    keep drawing (a later sibling follows) and whether it should paint active
    (white, vs grey) because a live descendant sits somewhere along that column.
    Depth-0 agents are siblings off the implicit main thread and DO get their
    own elbow.

    Returns ``(sub, depth, is_last_child, has_children, ancestor_continues,
    ancestor_active, own_active)``. ``ancestor_continues``/``ancestor_active``
    have one entry per ancestor level (0-indexed) up to this node's own depth.
    ``own_active`` colours this row's own elbow/branch glyph. Where a column is
    shared by multiple rows (a tree "trunk"), active wins.
    '''
    children, roots = _build_tree_index(subs)
    out: list[tuple[RunningSubagent, int, bool, bool, tuple[bool, ...], tuple[bool, ...], bool]] = []

    def walk(
        sub: RunningSubagent,
        depth: int,
        last: bool,
        own_later_active: bool,
        ancestors: tuple[bool, ...],
        ancestors_active: tuple[bool, ...],
    ) -> None:
        kids = children.get(id(sub), [])
        own_active = _subtree_has_active(sub, children)
        out.append((sub, depth, last, bool(kids), ancestors, ancestors_active, own_active))
        # Column colour for child i = (later child of sub is active) OR
        # (sub itself has a later, active sibling — own_later_active): both
        # draw through the same shared column, so either can keep it active.
        child_ancestors = ancestors + (not last,)
        for i, kid in enumerate(kids):
            kid_later_active   = any(_subtree_has_active(sib, children) for sib in kids[i + 1:])
            column_active      = kid_later_active or own_later_active
            child_ancestors_active = ancestors_active + (column_active,)
            walk(kid, depth + 1, i == len(kids) - 1, kid_later_active, child_ancestors, child_ancestors_active)

    for i, root in enumerate(roots):
        root_later_active = any(_subtree_has_active(r, children) for r in roots[i + 1:])
        walk(root, 0, i == len(roots) - 1, root_later_active, (), ())
    return out


def group_trees(subs: list[RunningSubagent]) -> list[list[RunningSubagent]]:
    '''Group a candidate cohort into parent-rooted trees: each group is a root
    plus every transitive descendant (discovery order); groups are returned in
    root first_timestamp order.'''
    children, roots = _build_tree_index(subs)

    def collect(sub: RunningSubagent, out: list[RunningSubagent]) -> None:
        out.append(sub)
        for kid in children.get(id(sub), []):
            collect(kid, out)

    groups: list[list[RunningSubagent]] = []
    for root in roots:
        group: list[RunningSubagent] = []
        collect(root, group)
        groups.append(group)
    return groups


def cap_tree_groups(subs: list[RunningSubagent], cap: int) -> list[RunningSubagent]:
    '''Cap a visible cohort for tree mode without splitting a parent from a
    still-active child. Groups into parent-rooted trees (group_trees) and evicts
    whole groups — finished groups first (oldest max end_ts), then active groups
    (oldest max mtime) — until count <= cap. A group is never evicted to zero:
    once one group remains and still exceeds cap, it's trimmed in place (root
    kept, most-recently-active cap - 1 descendants kept).'''
    groups = group_trees(subs)
    total = sum(len(g) for g in groups)
    if total <= cap:
        return subs

    finished = sorted(
        (g for g in groups if all(sub.end_ts > 0 for sub in g)),
        key=lambda g: max(sub.end_ts for sub in g),
    )
    active = sorted(
        (g for g in groups if any(sub.end_ts == 0 for sub in g)),
        key=lambda g: max(sub.mtime for sub in g),
    )

    kept = groups[:]
    for g in finished:
        if total <= cap or len(kept) == 1:
            break
        kept.remove(g)
        total -= len(g)
    if total > cap:
        for g in active:
            if total <= cap or len(kept) == 1:
                break
            kept.remove(g)
            total -= len(g)

    kept_ids = {id(g) for g in kept}
    ordered = [g for g in groups if id(g) in kept_ids]

    if total > cap and len(ordered) == 1:
        # Sole surviving group still exceeds cap: trim in place, keeping the
        # root plus the most-recently-active cap - 1 descendants. Live members
        # always outrank finished ones regardless of recency.
        root, *descendants = ordered[0]
        keep_ids = {
            id(sub) for sub in
            sorted(
                descendants,
                key=lambda sub: (sub.end_ts == 0, sub.mtime if sub.end_ts == 0 else sub.end_ts),
                reverse=True,
            )[:cap - 1]
        }
        trimmed = [root] + [sub for sub in descendants if id(sub) in keep_ids]
        return trimmed

    return [sub for g in ordered for sub in g]


class RunningSubagent:
    __slots__ = (
        'agent_type', 'description', 'billed_in', 'output', 'first_timestamp',
        'model', 'cache_read_in', 'total_input', 'last_activity', 'end_ts',
        'mtime', 'agent_id', 'jsonl_path', 'parent_id', 'spawn_depth',
        'status', 'run_count', 'is_fork', 'resumed', 'run_start_ts',
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
        end_ts:          float = 0.0,  # authoritative <task-notification> ts; 0 while running
        mtime:           float = 0.0,  # transcript last-modified time (st_mtime)
        agent_id:        str = '',     # transcript filename stem; matches run-JSON agentId (workflow cohort)
        jsonl_path:      str = '',     # absolute path to this agent's transcript (for tool-count rescan)
        parent_id:       str = '',     # meta.json parentAgentId — spawner's agent id ('' → top-level)
        spawn_depth:     int = 0,      # meta.json spawnDepth (1 = spawned by main; 0 when absent)
        status:          str = 'running',  # "running"|"completed"|"killed"|"failed"|"stopped"
        run_count:       int = 0,      # <task-notification> occurrences seen for this agent; 0 while never finished
        is_fork:         bool = False,  # meta.json "isFork" (equivalently agentType == "fork")
        resumed:         bool = False,  # a later notification/activity postdates the last-seen notification
        run_start_ts:    float | None = None,  # start of the CURRENT run; see subagent_dur_str
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
        self.jsonl_path       = jsonl_path
        self.parent_id        = parent_id
        self.spawn_depth      = spawn_depth
        self.status           = status
        self.run_count        = run_count
        self.is_fork          = is_fork
        self.resumed          = resumed
        # Start of the CURRENT run (not original spawn); see subagent_dur_str.
        self.run_start_ts     = run_start_ts if run_start_ts is not None else first_timestamp

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RunningSubagent):
            return NotImplemented
        return self._key() == other._key()

    def _key(self) -> tuple[object, ...]:
        return (
            self.agent_type, self.description, self.billed_in, self.output,
            self.first_timestamp, self.model, self.cache_read_in, self.total_input,
            self.last_activity, self.end_ts, self.mtime, self.agent_id,
            self.jsonl_path, self.parent_id, self.spawn_depth,
            self.status, self.run_count, self.is_fork, self.resumed,
            self.run_start_ts,
        )

    __hash__ = None  # type: ignore[assignment]

    @property
    def is_done(self) -> bool:
        '''Derived, not stored: true once an authoritative end_ts is set.'''
        return self.end_ts > 0

    def __repr__(self) -> str:
        return (f'RunningSubagent(agent_type={self.agent_type!r}, description={self.description!r}, '
                f'billed_in={self.billed_in}, output={self.output}, first_timestamp={self.first_timestamp}, '
                f'model={self.model!r}, cache_read_in={self.cache_read_in}, total_input={self.total_input}, '
                f'last_activity={self.last_activity!r}, end_ts={self.end_ts}, mtime={self.mtime}, '
                f'agent_id={self.agent_id!r}, jsonl_path={self.jsonl_path!r}, '
                f'parent_id={self.parent_id!r}, spawn_depth={self.spawn_depth}, '
                f'status={self.status!r}, run_count={self.run_count}, is_fork={self.is_fork}, '
                f'resumed={self.resumed}, run_start_ts={self.run_start_ts})')


class RunningSubagents:
    __slots__ = ('subagents', 'totals_only_ids')

    def __init__(self, subagents: list[RunningSubagent] | None = None, totals_only_ids: dict[str, float] | None = None) -> None:
        self.subagents = subagents if subagents is not None else []
        # agent_id -> boundary_ts for totals_only-parsed agents; visible() uses this to re-parse full.
        self.totals_only_ids = totals_only_ids if totals_only_ids is not None else {}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RunningSubagents):
            return NotImplemented
        return self.subagents == other.subagents

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'RunningSubagents(subagents={self.subagents!r})'

    # Seconds after last end_ts before a fully-Done cohort retires.
    COHORT_GRACE_SECONDS = 120
    # Total-silence threshold to sweep a dirty cohort; also the no-marker recency fallback.
    JANITOR_HORIZON_SECONDS = 60
    # Silence threshold for a still-running (end_ts == 0) member before it's orphaned, not merely quiet.
    ABANDONED_HORIZON_SECONDS = 1800
    # Silence threshold for "still writing" vs "idle/done".
    LIVENESS_WINDOW_SECONDS = 30
    # How long a Done member of a still-dirty cohort stays visible after end_ts (a
    # maximum — cap_tree_groups can still evict it early under room pressure).
    FINISHED_LINGER_SECONDS = 120
    # How far a write may postdate a terminal end_ts and still count as clock skew.
    TERMINAL_SKEW_SECONDS = 5
    STALE_SECONDS = LIVENESS_WINDOW_SECONDS  # alias for older callers

    @classmethod
    def from_session(
        cls,
        session_id: str,
        project_dir: str,
        now: float | None = None,
        *,
        cache: TranscriptCache | None = None,
    ) -> RunningSubagents:
        if not session_id or not project_dir:
            return cls()
        # now is injectable for deterministic tests.
        if now is None:
            now = time.time()
        # Match Claude Code's projects/ dir convention: non-alphanumeric -> '-'
        # (works on both Unix and Windows path shapes).
        project_slug = re.sub(r'[^A-Za-z0-9]', '-', project_dir)
        session_dir = projects_dir() / project_slug / session_id
        subagents_dir = session_dir / 'subagents'
        if not subagents_dir.is_dir():
            return cls()
        # Authoritative completion source: <task-notification> records across the
        # session .jsonl and every subagents/agent-*.jsonl, keyed by task-id.
        session_jsonl = projects_dir() / project_slug / f'{session_id}.jsonl'
        notif_map = _collect_task_notifications(session_jsonl, subagents_dir, cache=cache)
        subagents: list[RunningSubagent] = []
        totals_only_ids: dict[str, float] = {}
        try:
            for meta in subagents_dir.glob('*.meta.json'):
                agent_type = ''
                description = ''
                parent_id = ''
                spawn_depth = 0
                is_fork = False
                meta_model = ''
                tool_use_id = ''
                try:
                    data = json.loads(meta.read_text())
                    agent_type = _sanitize(data.get('agentType', '') or '')
                    description = _sanitize(data.get('description', '') or '')
                    # Absent in older metas -> top-level fallback.
                    parent_id = str(data.get('parentAgentId', '') or '')
                    raw_depth = data.get('spawnDepth', 0)
                    spawn_depth = int(raw_depth) if isinstance(raw_depth, (int, float)) else 0
                    is_fork = bool(data.get('isFork', False)) or agent_type == 'fork'
                    meta_model = str(data.get('model', '') or '')
                    # Join key for the tier-1 toolUseResult signal below.
                    tool_use_id = str(data.get('toolUseId', '') or '')
                except Exception:
                    continue
                # Spawning transcript: top-level session file, or the parent
                # agent's own transcript for a nested spawn.
                parent_jsonl = subagents_dir / f'agent-{parent_id}.jsonl' if parent_id else session_jsonl

                jsonl = meta.with_suffix('').with_suffix('.jsonl')
                if not jsonl.is_file():
                    continue
                try:
                    st = jsonl.stat()
                    mtime = st.st_mtime
                except OSError:
                    continue

                # Authoritative status, checked in priority order:
                # Tier 1 (preferred): the spawning transcript's own structured
                # toolUseResult.status ('completed' only; other values untrusted).
                # Tier 2 (below): <task-notification> scan. Tier 3 (below the parse
                # call): staleness fallback. Tiers 1/2 resolve before the parse so
                # notif_ts/prev_notif_ts can pick its resume boundary.
                status        = 'running'
                run_count     = 0
                notif_ts      = 0.0
                prev_notif_ts = 0.0
                end_ts        = 0.0
                if tool_use_id and parent_jsonl.is_file():
                    tool_result = _tail_read_tool_results(parent_jsonl, cache=cache).get(tool_use_id)
                    if tool_result is not None and tool_result[0] == 'completed':
                        status = 'completed'
                        end_ts = tool_result[1] if tool_result[1] > 0 else mtime

                # Tier 2: <task-notification> scan. Always feeds run_count/resumed
                # bookkeeping; only overrides status if tier 1 left it 'running'.
                task_id = jsonl.stem.removeprefix('agent-')
                lookup = notif_map.get(task_id) or notif_map.get(jsonl.stem)
                if lookup is not None:
                    run_count     = lookup.notif_count
                    notif_ts      = lookup.ts
                    prev_notif_ts = lookup.prev_ts
                    raw_status = lookup.status
                    if status == 'running' and raw_status in _TERMINAL_STATUSES:
                        status = raw_status
                        end_ts = notif_ts
                # Resumed: >1 notification seen, or the transcript kept being
                # written after the last-seen notification.
                resumed = run_count > 1 or (notif_ts > 0 and mtime > notif_ts)

                # Invalidate a terminal signal the transcript has since outlived
                # (write postdates end_ts by more than clock-skew tolerance) —
                # e.g. a stall watchdog marking a still-working agent failed.
                if end_ts > 0 and mtime - end_ts > cls.TERMINAL_SKEW_SECONDS:
                    status = 'running'
                    end_ts = 0.0

                # Per-run start boundary for duration display (subagent_dur_str):
                # still running -> latest notification (or 0.0 -> first_timestamp);
                # finished + resumed -> second-to-last notification (bracketing the
                # DISPLAYED run, not collapsing duration onto end_ts); else 0.0.
                if status == 'running':
                    boundary_ts = notif_ts
                elif run_count > 1:
                    boundary_ts = prev_notif_ts if prev_notif_ts > 0 else notif_ts
                else:
                    boundary_ts = 0.0

                use_totals_only = False
                if cache is not None and _conclusively_retired(now, status, end_ts, mtime):
                    if not cache.is_terminal(str(jsonl), st):
                        use_totals_only = True
                        totals_only_ids[jsonl.stem] = boundary_ts

                billed_in, cache_read_in, output, first_ts, model, last_activity, transcript_end_ts, parsed_run_start = (
                    parse_transcript(jsonl, boundary_ts, cache=cache, st=st, totals_only=use_totals_only)
                )

                if cache is not None and _conclusively_retired(now, status, end_ts, mtime):
                    cache.mark_terminal(str(jsonl))

                if meta_model:
                    model = meta_model

                run_start_ts = (
                    (parsed_run_start if parsed_run_start > 0 else boundary_ts)
                    if boundary_ts > 0 else first_ts
                )

                # Tier 3 (last resort): tiers 1/2 never fired, but the last line
                # carries end_turn AND the transcript has been silent for
                # ABANDONED_HORIZON_SECONDS — gating on both avoids the
                # end_turn-only false positive on a normal fast finish.
                if status == 'running' and transcript_end_ts > 0 and now - mtime > cls.ABANDONED_HORIZON_SECONDS:
                    status = 'completed'
                    end_ts = mtime

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
                    agent_id        = jsonl.stem,
                    jsonl_path      = str(jsonl),
                    parent_id       = parent_id,
                    spawn_depth     = spawn_depth,
                    status          = status,
                    run_count       = run_count,
                    is_fork         = is_fork,
                    resumed         = resumed,
                    run_start_ts    = run_start_ts,
                ))
        except OSError:
            pass
        subagents.sort(key=lambda s: s.first_timestamp)
        return cls(subagents=subagents, totals_only_ids=totals_only_ids)

    @classmethod
    def _live_ancestors(cls, subs: list[RunningSubagent], now: float) -> set[int]:
        '''ids of agents with a still-writing descendant. An agent is live when
        end_ts == 0 and written within LIVENESS_WINDOW_SECONDS; walking up each
        live agent's parent chain marks the whole branch above it.'''
        by_id: dict[str, RunningSubagent] = {}
        for sub in subs:
            if sub.agent_id:
                by_id[sub.agent_id] = sub
                by_id[sub.agent_id.removeprefix('agent-')] = sub
        ancestors: set[int] = set()
        for sub in subs:
            if sub.end_ts > 0 or now - sub.mtime > cls.LIVENESS_WINDOW_SECONDS:
                continue
            parent = by_id.get(sub.parent_id) if sub.parent_id else None
            # The membership guard also terminates on a parent_id cycle.
            while parent is not None and parent is not sub and id(parent) not in ancestors:
                ancestors.add(id(parent))
                parent = by_id.get(parent.parent_id) if parent.parent_id else None
        return ancestors

    def visible(self, now: float, last_prompt_ts: float | None) -> list[RunningSubagent]:
        '''Compute the turn-scoped cohort visible in the statusline.

        With last_prompt_ts: a candidate started this turn (first_timestamp >=
        last_prompt_ts), OR is still being written (within LIVENESS_WINDOW_SECONDS),
        OR has a live descendant (supervising parent, transcript-silent).
        Without last_prompt_ts: JANITOR_HORIZON_SECONDS recency window fallback,
        or still running (end_ts == 0).

        Retirement: all-Done candidates hide past COHORT_GRACE_SECONDS since
        max(end_ts); a dirty cohort hides once every member is silent for
        JANITOR_HORIZON_SECONDS.
        '''
        if last_prompt_ts is not None:
            # Supervising-parent keep: a parent blocked on its children writes
            # nothing, so mtime alone would evict it and re-root live children.
            live_parents = self._live_ancestors(self.subagents, now)
            candidates = [
                sub for sub in self.subagents
                if sub.first_timestamp >= last_prompt_ts
                or now - sub.mtime <= self.LIVENESS_WINDOW_SECONDS
                or id(sub) in live_parents
            ]
        else:
            candidates = [
                sub for sub in self.subagents
                if now - sub.mtime <= self.JANITOR_HORIZON_SECONDS
                or sub.end_ts == 0
            ]

        if not candidates:
            return []

        # Retirement is per-member, not all-or-nothing: a live sibling must not
        # keep a long-finished member visible forever.
        all_done = all(sub.end_ts > 0 for sub in candidates)

        def _retired(sub: RunningSubagent) -> bool:
            if sub.end_ts > 0:
                horizon = self.COHORT_GRACE_SECONDS if all_done else self.FINISHED_LINGER_SECONDS
                return now - sub.end_ts > horizon
            # No terminal signal: require the much longer ABANDONED_HORIZON_SECONDS
            # before treating silence as evidence of death.
            return now - sub.mtime > self.ABANDONED_HORIZON_SECONDS

        visible_list = [sub for sub in candidates if not _retired(sub)]

        # Re-parse agents cached in totals_only mode (blanked model/last_activity)
        # if still visible, to restore full-fidelity values.
        if self.totals_only_ids:
            reparsed_subs = {}
            for sub in visible_list:
                if sub.agent_id in self.totals_only_ids:
                    boundary_ts = self.totals_only_ids[sub.agent_id]
                    jsonl = Path(sub.jsonl_path)
                    try:
                        billed_in, cache_read_in, output, first_ts, model, last_activity, end_ts, parsed_run_start = (
                            parse_transcript(jsonl, boundary_ts, totals_only=False)
                        )
                        sub_rebuilt = RunningSubagent(
                            agent_type      = sub.agent_type,
                            description     = sub.description,
                            billed_in       = billed_in,
                            output          = output,
                            first_timestamp = first_ts,
                            model           = model,
                            cache_read_in   = cache_read_in,
                            total_input     = billed_in + cache_read_in,
                            last_activity   = last_activity,
                            end_ts          = sub.end_ts,
                            mtime           = sub.mtime,
                            agent_id        = sub.agent_id,
                            jsonl_path      = sub.jsonl_path,
                            parent_id       = sub.parent_id,
                            spawn_depth     = sub.spawn_depth,
                            status          = sub.status,
                            run_count       = sub.run_count,
                            is_fork         = sub.is_fork,
                            resumed         = sub.resumed,
                            run_start_ts    = parsed_run_start if parsed_run_start > 0 else boundary_ts if boundary_ts > 0 else first_ts,
                        )
                        reparsed_subs[id(sub)] = sub_rebuilt
                    except OSError:
                        pass

            if reparsed_subs:
                self.subagents = [reparsed_subs.get(id(s), s) for s in self.subagents]
                visible_list = [reparsed_subs.get(id(s), s) for s in visible_list]
                self.totals_only_ids.clear()

        return visible_list

    @staticmethod
    def _parse_transcript(
        jsonl: Path, resume_after: float = 0.0,
    ) -> tuple[int, int, int, float, str, tuple[str, str, dict[str, object]], float, float]:
        # Thin delegator kept for existing callers/tests of this name.
        return parse_transcript(jsonl, resume_after)


def _conclusively_retired(now: float, status: str, end_ts: float, mtime: float) -> bool:
    '''Conservative predicate: True only when an agent is provably permanently done —
    terminal status, end_ts > 0, end_ts older than FINISHED_LINGER/COHORT_GRACE +
    TERMINAL_SKEW, and mtime older than ABANDONED_HORIZON + TERMINAL_SKEW. False
    negatives are harmless (agent stays listed longer); false positives are caught
    by visible()'s re-parse. Used to gate cache.mark_terminal and totals_only parsing.
    '''
    return (
        status in _TERMINAL_STATUSES
        and end_ts > 0
        and now - end_ts > max(
            RunningSubagents.FINISHED_LINGER_SECONDS,
            RunningSubagents.COHORT_GRACE_SECONDS,
        ) + RunningSubagents.TERMINAL_SKEW_SECONDS
        and now - mtime > RunningSubagents.ABANDONED_HORIZON_SECONDS + RunningSubagents.TERMINAL_SKEW_SECONDS
    )
