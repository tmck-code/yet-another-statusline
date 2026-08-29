"""Transcript parse cache — per-session persistence of transcript parses and derived counts.

Pure performance cache: every value is re-derivable from the transcript. Any
doubt about validity resolves to a miss.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from yas.info.subagents import _Notification

from yas.constants import (
    TRANSCRIPT_CACHE_VERSION,
    TRANSCRIPT_CACHE_KEEP_SECONDS,
    TRANSCRIPT_CACHE_SUBKEY_MAX,
    transcript_cache_path,
)


def cache_path(session_id: str) -> Path:
    return transcript_cache_path(session_id)


class TranscriptCache:
    """Cached parses and derived stats from a transcript, keyed by str(path) and
    sub-keyed by parse inputs. Whole-file results (parse, counts) are validated
    by exact (mtime, size) match; tail-state results (notif, tres) are returned
    regardless and the CALLER validates.
    """

    __slots__ = ('session_id', '_entries', '_dirty')

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._entries: dict[str, dict[str, object]] = {}
        self._dirty = False

    @classmethod
    def load(cls, session_id: str) -> TranscriptCache:
        """Load the cache for a session; empty instance on any failure (missing,
        unreadable, bad version/session, malformed entries)."""
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

            # Drop malformed entries.
            for path_key, entry in entries.items():
                if isinstance(entry, dict):
                    cache._entries[path_key] = entry

            cache._dirty = False
            return cache
        except Exception:
            # Missing, unreadable, invalid JSON, etc. Return empty cache.
            return cache

    def _entry(self, path: str, st: os.stat_result) -> dict[str, object] | None:
        """Entry if (mtime, size) match exactly; else drop stale parse/counts and return None."""
        if path not in self._entries:
            return None

        entry = self._entries[path]
        stored_mtime = entry.get('mtime')
        stored_size = entry.get('size')

        if stored_mtime != st.st_mtime or stored_size != st.st_size:
            entry.pop('parse', None)
            entry.pop('counts', None)
            return None

        return entry

    def _stamp_entry(self, path: str, st: os.stat_result) -> dict[str, object]:
        """entries[path] (creating if absent), stamped with file metadata + access time."""
        entry = self._entries.setdefault(path, {})
        entry['mtime'] = st.st_mtime
        entry['size'] = st.st_size
        entry['seen'] = time.time()
        self._dirty = True
        return entry

    @staticmethod
    def _put_recency(subkey_map: dict[str, object], subkey: str, value: object) -> None:
        """Insert/overwrite subkey_map[subkey] = value, then trim to
        TRANSCRIPT_CACHE_SUBKEY_MAX entries by recency of write (LRU), not key string.
        Relies on dict insertion order: pop-then-reinsert moves subkey to the end."""
        subkey_map.pop(subkey, None)
        subkey_map[subkey] = value
        if len(subkey_map) > TRANSCRIPT_CACHE_SUBKEY_MAX:
            for old_key in list(subkey_map)[:-TRANSCRIPT_CACHE_SUBKEY_MAX]:
                del subkey_map[old_key]

    def get_parse(
        self, path: str, st: os.stat_result, resume_after: float
    ) -> tuple[int, int, int, float, str, tuple[str, str, dict[str, object]], float, float] | None:
        """Cached parse result for (path, resume_after), re-tupled to the 8-field
        shape, or None on absence/shape mismatch."""
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
        """Cache a parse result, sub-keyed by repr(float(resume_after))."""
        entry = self._stamp_entry(path, st)

        if 'parse' not in entry or not isinstance(entry['parse'], dict):
            entry['parse'] = {}

        parses = cast('dict[str, object]', entry['parse'])
        subkey = repr(float(resume_after))

        if not (len(result) == 8 and isinstance(result[5], tuple) and len(result[5]) == 3):
            return

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
        self._put_recency(parses, subkey, stored)

    def get_counts(
        self,
        path: str,
        st: os.stat_result,
        clear_epoch: float | None,
        skip_sidechain: bool,
    ) -> dict[str, object] | None:
        """Cached {'counts', 'lines_read', 'lines_changed'} result, or None on mismatch/staleness."""
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
        """Cache a counts result, sub-keyed by f'{clear_epoch!r}|{int(skip_sidechain)}'."""
        entry = self._stamp_entry(path, st)

        if 'counts' not in entry or not isinstance(entry['counts'], dict):
            entry['counts'] = {}

        counts_map = cast('dict[str, object]', entry['counts'])
        subkey = f'{clear_epoch!r}|{int(skip_sidechain)}'
        self._put_recency(counts_map, subkey, result)

    def _notif_to_json(self, n: '_Notification') -> list[object]:
        """[task_id, tool_use_id, status, ts]."""
        return [n.task_id, n.tool_use_id, n.status, n.ts]

    def _notif_from_json(self, seq: object) -> '_Notification | None':
        """Inverse of _notif_to_json, or None on mismatch."""
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
        """Cached (mtime, size, offset, items) or None. Returned regardless of
        current (mtime, size) — the CALLER validates."""
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
        """Cache notification state."""
        if path not in self._entries:
            self._entries[path] = {}

        entry = self._entries[path]
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
        """Cached (mtime, size, offset, {tool_use_id: (status, ts)}) or None.
        Returned regardless of current (mtime, size) — the CALLER validates."""
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
        """Cache tool results state."""
        if path not in self._entries:
            self._entries[path] = {}

        entry = self._entries[path]
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

    def mark_terminal(self, path: str) -> None:
        """Mark a transcript as terminal (will not grow further); still subject to age-pruning."""
        if path not in self._entries:
            self._entries[path] = {}

        entry = self._entries[path]
        entry['terminal'] = True
        self._dirty = True

    def is_terminal(self, path: str, st: os.stat_result) -> bool:
        """True iff marked terminal AND (mtime, size) still match (a changed file is never terminal)."""
        if path not in self._entries:
            return False

        entry = self._entries[path]

        if not entry.get('terminal', False):
            return False

        stored_mtime = entry.get('mtime')
        stored_size = entry.get('size')

        if stored_mtime != st.st_mtime or stored_size != st.st_size:
            return False

        return True

    def save(self) -> None:
        """Save to disk (atomic write via .tmp + os.replace), pruning entries whose
        path is gone or whose 'seen' exceeds TRANSCRIPT_CACHE_KEEP_SECONDS. No-op when not dirty."""
        if not self._dirty:
            return

        path = cache_path(self.session_id)
        now = time.time()

        entries_to_keep = {}
        for path_key, entry in self._entries.items():
            if not os.path.exists(path_key):
                continue

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
