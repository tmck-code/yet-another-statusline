"""Transcript parse cache — per-session persistence of transcript parses and derived counts.

This is a pure performance cache; every stored value is re-derivable from the
transcript. Any doubt about validity resolves to a miss. Nothing here may
ever change rendered output.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

if TYPE_CHECKING:
    from yas.info.subagents import _Notification
    from yas.info.transcript import TranscriptUsage

from yas.constants import (
    TRANSCRIPT_CACHE_VERSION,
    TRANSCRIPT_CACHE_KEEP_SECONDS,
    TRANSCRIPT_CACHE_SUBKEY_MAX,
    transcript_cache_path,
)


_S = TypeVar('_S')


def cache_path(session_id: str) -> Path:
    """Return the cache file path for a session.

    Delegates to yas.constants.transcript_cache_path(), which resolves
    CLAUDE_DIR at call time — so a test's monkeypatch of
    yas.constants.CLAUDE_DIR reaches this too. Path lives under the
    consolidated yas/cache/ tree (see yas.constants.cache_dir()), not the
    old top-level yas-cache/ directory.
    """
    return transcript_cache_path(session_id)


FOLD_CHECK_BYTES = 64


def _check_hex(path: str, offset: int) -> str | None:
    """Return the hex of the FOLD_CHECK_BYTES bytes just before `offset`, or None on read error."""
    start = max(0, offset - FOLD_CHECK_BYTES)
    try:
        with open(path, 'rb') as f:
            f.seek(start)
            return f.read(offset - start).hex()
    except OSError:
        return None


def read_complete_lines(path: str, offset: int) -> tuple[bytes, int, str]:
    """Read from `offset` up to and including the last newline byte.

    Returns (chunk, new_offset, check). A half-written trailing line is not
    consumed. `check` is the hex of the FOLD_CHECK_BYTES bytes ending at
    new_offset (the prefix identity for the next resume). Raises OSError.
    """
    start = max(0, offset - FOLD_CHECK_BYTES)
    with open(path, 'rb') as f:
        f.seek(start)
        head = f.read(offset - start)
        data = f.read()

    cut = data.rfind(b'\n') + 1
    chunk = data[:cut]
    tail = (head + chunk)[-FOLD_CHECK_BYTES:]
    return chunk, offset + cut, tail.hex()


def fold_file(
    cache: 'TranscriptCache | None',
    path: str,
    st: os.stat_result | None,
    key: str,
    subkey: str,
    init: Callable[[], _S],
    fold: Callable[[_S, list[bytes]], _S],
    version: int = 0,
) -> _S:
    """Resume or restart an incremental fold over the complete lines of `path`.

    init() returns a fresh JSON-serialisable state; fold(state, lines) returns
    the new state for the given new complete lines (bytes, no newline). With
    cache=None this is a full parse with no store. An unreadable file yields
    init() and stores nothing. `version` is the schema version of the state:
    bump it whenever init()/fold() change the state shape, so entries stored
    under an older shape are re-folded from 0 instead of resumed.
    """
    state = init()
    offset = 0
    if cache is not None and st is not None:
        hit = cache.get_fold(path, st, key, subkey, version)
        if hit is not None:
            state, offset = hit

    try:
        chunk, new_offset, check = read_complete_lines(path, offset)
    except OSError:
        return init()

    if not chunk:
        return state

    state = fold(state, chunk.split(b'\n')[:-1])
    if cache is not None and st is not None:
        cache.put_fold(path, st, key, subkey, state, new_offset, check, version)
    return state


class TranscriptCache:
    """Cached parses and derived stats from a transcript.

    Entries are keyed by str(path) and sub-keyed by parse inputs (resume_after,
    clear_epoch, skip_sidechain) or tail-state identifiers. Each entry tracks
    (mtime, size) to detect stale data. Whole-file results (parse, counts) are
    validated by exact (mtime, size) match; tail-state results (notif, tres)
    are returned regardless and the CALLER validates.
    """

    __slots__ = ('session_id', '_entries', '_dirty')

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._entries: dict[str, dict[str, object]] = {}
        self._dirty = False

    @classmethod
    def load(cls, session_id: str) -> TranscriptCache:
        """Load the cache for a session, or return an empty instance on any failure.

        Returns an empty instance when the file is missing, unreadable, non-JSON,
        not a dict, has v != TRANSCRIPT_CACHE_VERSION, has a session field that
        does not match, or any entry is malformed. Blanket except Exception.
        """
        cache = cls(session_id)
        path = cache_path(session_id)

        if not path.exists():
            return cache

        try:
            text = path.read_text()
            data = json.loads(text)

            if not isinstance(data, dict):
                return cache

            if data.get('v') != TRANSCRIPT_CACHE_VERSION:
                return cache

            if data.get('session') != session_id:
                return cache

            entries = data.get('entries', {})
            if not isinstance(entries, dict):
                return cache

            # Load entries; drop any that are malformed.
            for path_key, entry in entries.items():
                if not isinstance(entry, dict):
                    continue
                # Validate top-level entry shape.
                try:
                    cache._entries[path_key] = entry
                except Exception:
                    # Drop malformed entry.
                    continue

            cache._dirty = False
            return cache
        except Exception:
            # Missing, unreadable, invalid JSON, etc. Return empty cache.
            return cache

    def _entry(self, path: str, st: os.stat_result) -> dict[str, object] | None:
        """Return the stored entry if (mtime, size) match; else drop stale results.

        Exact float comparison, no epsilon. Drops parse and counts but preserves
        mtime/size so a changed file is always re-read. Returns None when absent
        or stale.
        """
        if path not in self._entries:
            return None

        entry = self._entries[path]
        stored_mtime = entry.get('mtime')
        stored_size = entry.get('size')

        if stored_mtime != st.st_mtime or stored_size != st.st_size:
            # Stale: drop whole-file results but keep entry structure.
            entry.pop('parse', None)
            entry.pop('counts', None)
            return None

        return entry

    def get_parse(
        self, path: str, st: os.stat_result, resume_after: float
    ) -> tuple[int, int, int, float, str, tuple[str, str, dict[str, object]], float, float] | None:
        """Return cached parse result for (path, resume_after) or None.

        On load, re-tuple the stored 8-list into
        (int, int, int, float, str, (str, str, dict), float, float).
        Validates shape (length 8, element 5 a 3-sequence) and returns None
        on any mismatch.
        """
        entry = self._entry(path, st)
        if entry is None:
            return None

        parses = entry.get('parse', {})
        if not isinstance(parses, dict):
            return None

        subkey = repr(float(resume_after))
        stored = parses.get(subkey)

        if stored is None:
            return None

        try:
            if not isinstance(stored, list) or len(stored) != 8:
                return None

            # Element 5 should be a 3-sequence (str, str, dict).
            if not isinstance(stored[5], (list, tuple)) or len(stored[5]) != 3:
                return None

            # Re-tuple: convert 8-list to tuple.
            result = (
                int(stored[0]),
                int(stored[1]),
                int(stored[2]),
                float(stored[3]),
                str(stored[4]),
                (str(stored[5][0]), str(stored[5][1]), dict(stored[5][2])),
                float(stored[6]),
                float(stored[7]),
            )
            return result
        except (TypeError, ValueError, KeyError):
            return None

    def put_parse(
        self,
        path: str,
        st: os.stat_result,
        resume_after: float,
        result: tuple[int, int, int, float, str, tuple[str, str, dict[str, object]], float, float],
    ) -> None:
        """Cache a parse result.

        Sub-key is repr(float(resume_after)). Trims the sub-map to the newest
        TRANSCRIPT_CACHE_SUBKEY_MAX entries.
        """
        if path not in self._entries:
            self._entries[path] = {}

        entry = self._entries[path]

        # Stamp entry with file metadata and current time.
        entry['mtime'] = st.st_mtime
        entry['size'] = st.st_size
        entry['seen'] = time.time()
        self._dirty = True

        if 'parse' not in entry or not isinstance(entry['parse'], dict):
            entry['parse'] = {}

        parses = cast('dict[str, object]', entry['parse'])
        subkey = repr(float(resume_after))

        # Convert tuple to list for JSON serialization.
        if len(result) == 8 and isinstance(result[5], tuple) and len(result[5]) == 3:
            stored = [
                result[0],
                result[1],
                result[2],
                result[3],
                result[4],
                list(result[5]),
                result[6],
                result[7],
            ]
            parses[subkey] = stored
        else:
            # Invalid shape; don't cache.
            return

        # Trim to newest TRANSCRIPT_CACHE_SUBKEY_MAX entries.
        if len(parses) > TRANSCRIPT_CACHE_SUBKEY_MAX:
            keys = sorted(parses.keys())
            for old_key in keys[:-TRANSCRIPT_CACHE_SUBKEY_MAX]:
                del parses[old_key]

    def get_counts(
        self,
        path: str,
        st: os.stat_result,
        clear_epoch: float | None,
        skip_sidechain: bool,
    ) -> dict[str, object] | None:
        """Return cached counts result or None.

        Shape is {'counts': {...}, 'lines_read': int, 'lines_changed': int}.
        Returns None on shape mismatch or stale entry.
        """
        entry = self._entry(path, st)
        if entry is None:
            return None

        counts_map = entry.get('counts', {})
        if not isinstance(counts_map, dict):
            return None

        subkey = f'{clear_epoch!r}|{int(skip_sidechain)}'
        stored = counts_map.get(subkey)

        if stored is None:
            return None

        try:
            if not isinstance(stored, dict):
                return None

            # Validate shape: must have 'counts', 'lines_read', 'lines_changed'.
            if 'counts' not in stored or 'lines_read' not in stored or 'lines_changed' not in stored:
                return None

            counts = stored.get('counts')
            lines_read = stored.get('lines_read')
            lines_changed = stored.get('lines_changed')

            if not isinstance(counts, dict) or not isinstance(lines_read, int) or not isinstance(lines_changed, int):
                return None

            return {
                'counts': counts,
                'lines_read': lines_read,
                'lines_changed': lines_changed,
            }
        except (TypeError, ValueError, KeyError):
            return None

    def put_counts(
        self,
        path: str,
        st: os.stat_result,
        clear_epoch: float | None,
        skip_sidechain: bool,
        result: dict[str, object],
    ) -> None:
        """Cache a counts result.

        Shape is {'counts': {...}, 'lines_read': int, 'lines_changed': int}.
        Sub-key is f'{clear_epoch!r}|{int(skip_sidechain)}'. Trims the sub-map
        to the newest TRANSCRIPT_CACHE_SUBKEY_MAX entries.
        """
        if path not in self._entries:
            self._entries[path] = {}

        entry = self._entries[path]

        # Stamp entry with file metadata and current time.
        entry['mtime'] = st.st_mtime
        entry['size'] = st.st_size
        entry['seen'] = time.time()
        self._dirty = True

        if 'counts' not in entry or not isinstance(entry['counts'], dict):
            entry['counts'] = {}

        counts_map = cast('dict[str, object]', entry['counts'])
        subkey = f'{clear_epoch!r}|{int(skip_sidechain)}'

        counts_map[subkey] = result

        # Trim to newest TRANSCRIPT_CACHE_SUBKEY_MAX entries.
        if len(counts_map) > TRANSCRIPT_CACHE_SUBKEY_MAX:
            keys = sorted(counts_map.keys())
            for old_key in keys[:-TRANSCRIPT_CACHE_SUBKEY_MAX]:
                del counts_map[old_key]

    def get_usage(self, path: str, st: os.stat_result) -> 'TranscriptUsage | None':
        """Return a cached TranscriptUsage for `path`, or None on miss/stale.

        Whole-file result, validated by exact (mtime, size) match like
        get_parse/get_counts. Used by `TranscriptUsage.from_session` to avoid
        re-parsing each subagent transcript on every render tick.
        """
        entry = self._entry(path, st)
        if entry is None:
            return None

        stored = entry.get('usage')
        if not isinstance(stored, list) or len(stored) != 6:
            return None

        from yas.info.transcript import TranscriptUsage
        try:
            return TranscriptUsage(
                input_tokens                = int(stored[0]),
                cache_creation_input_tokens = int(stored[1]),
                cache_read_input_tokens     = int(stored[2]),
                output_tokens               = int(stored[3]),
                cache_anchor_epoch          = float(stored[4]),
                cache_ttl                   = int(stored[5]),
            )
        except (TypeError, ValueError):
            return None

    def put_usage(self, path: str, st: os.stat_result, usage: 'TranscriptUsage') -> None:
        """Cache a TranscriptUsage for `path`, stamped with (mtime, size)."""
        if path not in self._entries:
            self._entries[path] = {}

        entry = self._entries[path]
        entry['mtime'] = st.st_mtime
        entry['size']  = st.st_size
        entry['seen']  = time.time()
        entry['usage'] = [
            usage.input_tokens,
            usage.cache_creation_input_tokens,
            usage.cache_read_input_tokens,
            usage.output_tokens,
            usage.cache_anchor_epoch,
            usage.cache_ttl,
        ]
        self._dirty = True

    def _notif_to_json(self, n: '_Notification') -> list[object]:
        """Convert a _Notification to a JSON-serializable list.

        Format: [task_id, tool_use_id, status, ts].
        """
        return [n.task_id, n.tool_use_id, n.status, n.ts]

    def _notif_from_json(self, seq: object) -> '_Notification | None':
        """Convert a JSON list back to a _Notification, or None on mismatch.

        Format: [task_id, tool_use_id, status, ts].
        """
        try:
            if not isinstance(seq, (list, tuple)) or len(seq) != 4:
                return None

            # Lazy import to avoid circular import with subagents.
            from yas.info.subagents import _Notification

            return _Notification(
                task_id=str(seq[0]),
                tool_use_id=str(seq[1]),
                status=str(seq[2]),
                ts=float(seq[3]),
            )
        except (TypeError, ValueError, IndexError):
            return None

    def get_notif(self, path: str) -> tuple[float, int, int, list['_Notification']] | None:
        """Return cached notification state (mtime, size, offset, items) or None.

        items is a list of _Notification objects (or [] if empty).
        Returned regardless of current (mtime, size) — the CALLER validates.
        """
        if path not in self._entries:
            return None

        entry = self._entries[path]
        notif_data = entry.get('notif')

        if notif_data is None:
            return None

        try:
            if not isinstance(notif_data, dict):
                return None

            mtime = notif_data.get('mtime')
            size = notif_data.get('size')
            offset = notif_data.get('offset')
            items_seq = notif_data.get('items', [])

            if mtime is None or size is None or offset is None:
                return None

            mtime = float(mtime)
            size = int(size)
            offset = int(offset)

            # Decode items list.
            items: list['_Notification'] = []
            for item_seq in items_seq:
                decoded = self._notif_from_json(item_seq)
                if decoded is not None:
                    items.append(decoded)

            return (mtime, size, offset, items)
        except (TypeError, ValueError, KeyError):
            return None

    def put_notif(
        self, path: str, mtime: float, size: int, offset: int, items: list['_Notification']
    ) -> None:
        """Cache notification state.

        items is a list of _Notification objects.
        """
        if path not in self._entries:
            self._entries[path] = {}

        entry = self._entries[path]

        # Encode items.
        encoded_items = [self._notif_to_json(item) for item in items]

        entry['notif'] = {
            'mtime': mtime,
            'size': size,
            'offset': offset,
            'items': encoded_items,
        }

        entry['seen'] = time.time()
        self._dirty = True

    def get_tool_results(self, path: str) -> tuple[float, int, int, dict[str, tuple[str, float]]] | None:
        """Return cached tool results state (mtime, size, offset, results) or None.

        results is a dict {tool_use_id: (status, ts), ...}.
        Returned regardless of current (mtime, size) — the CALLER validates.
        """
        if path not in self._entries:
            return None

        entry = self._entries[path]
        tres_data = entry.get('tres')

        if tres_data is None:
            return None

        try:
            if not isinstance(tres_data, dict):
                return None

            mtime = tres_data.get('mtime')
            size = tres_data.get('size')
            offset = tres_data.get('offset')
            results_seq = tres_data.get('results', {})

            if mtime is None or size is None or offset is None:
                return None

            mtime = float(mtime)
            size = int(size)
            offset = int(offset)

            # Decode results: convert [status, ts] back to (status, ts).
            results: dict[str, tuple[str, float]] = {}
            for tool_use_id, val in results_seq.items():
                if not isinstance(val, (list, tuple)) or len(val) != 2:
                    continue
                results[str(tool_use_id)] = (str(val[0]), float(val[1]))

            return (mtime, size, offset, results)
        except (TypeError, ValueError, KeyError):
            return None

    def put_tool_results(
        self, path: str, mtime: float, size: int, offset: int, results: dict[str, tuple[str, float]]
    ) -> None:
        """Cache tool results state.

        results is a dict {tool_use_id: (status, ts), ...}.
        """
        if path not in self._entries:
            self._entries[path] = {}

        entry = self._entries[path]

        # Convert tuples to lists for JSON.
        encoded_results = {}
        for tool_use_id, (status, ts) in results.items():
            encoded_results[str(tool_use_id)] = [status, ts]

        entry['tres'] = {
            'mtime': mtime,
            'size': size,
            'offset': offset,
            'results': encoded_results,
        }

        entry['seen'] = time.time()
        self._dirty = True

    def get_fold(
        self, path: str, st: os.stat_result, key: str, subkey: str = '', version: int = 0
    ) -> tuple[Any, int] | None:
        """Return (state, offset) for an incremental fold, or None to re-parse from 0.

        Valid only while dev/ino match `st`, st_size >= offset, and the stored
        prefix-check bytes still match the file and the stored state `version`
        (absent = 0) equals `version`. Independent of mtime.
        """
        entry = self._entries.get(path)
        folds = entry.get('fold') if entry is not None else None
        subs = folds.get(key) if isinstance(folds, dict) else None
        rec = subs.get(subkey) if isinstance(subs, dict) else None
        if not isinstance(rec, dict):
            return None

        offset = rec.get('off')
        if (
            rec.get('dev') != st.st_dev
            or rec.get('ino') != st.st_ino
            or not isinstance(offset, int)
            or st.st_size < offset
            or 'state' not in rec
            or rec.get('ver', 0) != version
        ):
            return None

        if _check_hex(path, offset) != rec.get('chk'):
            return None
        return rec['state'], offset

    def put_fold(
        self,
        path: str,
        st: os.stat_result,
        key: str,
        subkey: str,
        state: Any,
        offset: int,
        check: str,
        version: int = 0,
    ) -> None:
        """Store fold state at `offset`.

        Layout: entry['fold'][key][subkey] = {dev, ino, off, chk, state, ver}.
        Subkeys are trimmed to TRANSCRIPT_CACHE_SUBKEY_MAX.
        """
        entry = self._entries.setdefault(path, {})
        entry['seen'] = time.time()
        self._dirty = True

        folds = entry.get('fold')
        if not isinstance(folds, dict):
            folds = entry['fold'] = {}
        subs = folds.get(key)
        if not isinstance(subs, dict):
            subs = folds[key] = {}

        subs[subkey] = {
            'dev': st.st_dev, 'ino': st.st_ino, 'off': offset, 'chk': check, 'state': state, 'ver': version,
        }
        if len(subs) > TRANSCRIPT_CACHE_SUBKEY_MAX:
            for old_key in sorted(subs)[:-TRANSCRIPT_CACHE_SUBKEY_MAX]:
                del subs[old_key]

    def mark_terminal(self, path: str) -> None:
        """Mark a transcript as terminal (will not grow further).

        Entries are still subject to pruning by age.
        """
        if path not in self._entries:
            self._entries[path] = {}

        entry = self._entries[path]
        entry['terminal'] = True
        self._dirty = True

    def is_terminal(self, path: str, st: os.stat_result) -> bool:
        """Return True if the transcript is marked terminal AND (mtime, size) still match.

        A changed file is always considered non-terminal (re-read required).
        """
        if path not in self._entries:
            return False

        entry = self._entries[path]

        if not entry.get('terminal', False):
            return False

        # Validate (mtime, size) match.
        stored_mtime = entry.get('mtime')
        stored_size = entry.get('size')

        if stored_mtime != st.st_mtime or stored_size != st.st_size:
            return False

        return True

    def save(self) -> None:
        """Save the cache to disk, with pruning and atomic write.

        No-op when not _dirty. Prunes entries whose path no longer exists
        and entries whose seen is older than TRANSCRIPT_CACHE_KEEP_SECONDS.
        Writes to <path>.tmp then os.replace to <path> for atomicity.
        Whole body in try/except (OSError, TypeError, ValueError).
        """
        if not self._dirty:
            return

        path = cache_path(self.session_id)
        now = time.time()

        # Prune: drop entries whose path doesn't exist or are too old.
        entries_to_keep = {}
        for path_key, entry in self._entries.items():
            # Skip if path no longer exists.
            if not os.path.exists(path_key):
                continue

            # Skip if entry is too old.
            seen = entry.get('seen')
            if isinstance(seen, (int, float)) and (now - float(seen) > TRANSCRIPT_CACHE_KEEP_SECONDS):
                continue

            entries_to_keep[path_key] = entry

        data = {
            'v': TRANSCRIPT_CACHE_VERSION,
            'session': self.session_id,
            'saved': now,
            'entries': entries_to_keep,
        }

        tmp_path = path.parent / f'{path.name}.tmp'

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(json.dumps(data, separators=(',', ':')))
            os.replace(tmp_path, path)
        except (OSError, TypeError, ValueError):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
