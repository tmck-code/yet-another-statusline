from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class ActiveSession:
    session_id: str
    jsonl_path: Path
    jsonl_mtime: float
    payload: dict[str, object]
    payload_mtime: float


def find_active_jsonls(
    include_after: timedelta,
    now: datetime,
    projects_root: Path = Path.home() / '.claude' / 'projects',
) -> list[tuple[Path, float]]:
    """Return (jsonl_path, mtime) pairs for .jsonl files whose mtime is within include_after of now."""
    result: list[tuple[Path, float]] = []
    now_ts = now.timestamp()
    cutoff = include_after.total_seconds()

    if not projects_root.exists():
        return result

    for jsonl_path in projects_root.glob('*/*.jsonl'):
        try:
            mtime = jsonl_path.stat().st_mtime
        except OSError:
            continue
        if now_ts - mtime <= cutoff:
            result.append((jsonl_path, mtime))

    return result


def index_payloads_by_session(
    payloads_root: Path = Path.home() / '.claude' / 'statusline-output',
) -> dict[str, tuple[Path, float, dict[str, object]]]:
    """Return most-recent payload file per session_id as (path, mtime, parsed_dict)."""
    index: dict[str, tuple[Path, float, dict[str, object]]] = {}

    if not payloads_root.exists():
        return index

    for json_path in payloads_root.glob('*.json'):
        try:
            mtime = json_path.stat().st_mtime
            with open(json_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            continue

        session_id = data.get('session_id')
        if not session_id:
            continue

        existing = index.get(session_id)
        if existing is None or mtime > existing[1]:
            index[session_id] = (json_path, mtime, data)

    return index


def discover(
    include_after: timedelta,
    now: datetime,
    projects_root: Path | None = None,
    payloads_root: Path | None = None,
) -> list[ActiveSession]:
    """Return ActiveSession list for sessions with both an active jsonl and a payload.

    Roots are resolved from statusline.config.CLAUDE_DIR at call time (honouring
    CLAUDE_CONFIG_DIR), not from import-time Path.home() defaults — the renderer
    writes payloads under config.CLAUDE_DIR, so a CLAUDE_CONFIG_DIR user's
    sessions would otherwise be invisible to `mon` (Audit MON-1). Resolving via
    the config singleton's attribute (not os.environ) keeps the test sandbox's
    monkeypatched CLAUDE_DIR in effect. Explicit roots override (used by tests).
    """
    from statusline import config
    if projects_root is None:
        projects_root = config.CLAUDE_DIR / 'projects'
    if payloads_root is None:
        payloads_root = config.CLAUDE_DIR / 'statusline-output'
    active_jsonls = find_active_jsonls(include_after, now, projects_root)
    payload_index = index_payloads_by_session(payloads_root)

    sessions = []
    for jsonl_path, jsonl_mtime in active_jsonls:
        # session_id is the stem of the jsonl filename
        session_id = jsonl_path.stem
        entry = payload_index.get(session_id)
        if entry is None:
            continue
        payload_path, payload_mtime, payload = entry
        sessions.append(ActiveSession(
            session_id=session_id,
            jsonl_path=jsonl_path,
            jsonl_mtime=jsonl_mtime,
            payload=payload,
            payload_mtime=payload_mtime,
        ))

    sessions.sort(key=lambda s: (s.payload.get('cwd', ''), s.session_id))
    return sessions
