"""Clear-epoch reader — finds the most-recent /clear marker in a transcript."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from yas.constants import CLEAR_SCAN_MAX_LINES


def read_clear_epoch(transcript_path: str) -> float | None:
    """Epoch of the most-recent /clear marker within the first CLEAR_SCAN_MAX_LINES lines, or None."""
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
