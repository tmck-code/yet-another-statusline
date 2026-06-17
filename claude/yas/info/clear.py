"""Clear-epoch reader — finds the most-recent /clear marker in a transcript.

A /clear in Claude Code forks a new transcript and writes a user message
containing ``<command-name>/clear</command-name>`` near the top.  We scan
only the first CLEAR_SCAN_MAX_LINES lines so the lookup is O(1) on any
transcript length.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from yas.constants import CLEAR_SCAN_MAX_LINES


def read_clear_epoch(transcript_path: str) -> float | None:
    """Return the epoch of the most-recent /clear marker, or None.

    Returns None on: empty/missing path, OSError, JSON parse error,
    timestamp parse error, or no matching marker found within the first
    CLEAR_SCAN_MAX_LINES lines of the transcript.
    """
    if not transcript_path:
        return None
    p = Path(transcript_path)
    if not p.is_file():
        return None
    try:
        with p.open('r', errors='ignore') as fh:
            for _i, ln in enumerate(fh):
                if _i >= CLEAR_SCAN_MAX_LINES:
                    break
                if '/clear' not in ln or 'command-name' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except (ValueError, TypeError):
                    continue
                ts = d.get('timestamp', '') or ''
                if not ts:
                    continue
                try:
                    if ts.endswith('Z'):
                        ts = ts[:-1] + '+00:00'
                    return datetime.fromisoformat(ts).timestamp()
                except (ValueError, TypeError):
                    continue
    except OSError:
        return None
    return None
