"""Integration test for the multi-session observer pipeline.

Exercises discover → classify → aggregate → format_header without needing
claude/mon.py (Phase 7).  One end-to-end test per the task spec.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))

from claude.mon.layout import aggregate_day_cost, aggregate_rate_limits, format_header
from claude.mon.lifecycle import classify

_SESSION_A     = 'aaa-111'
_SESSION_B     = 'bbb-222'
_SESSION_STALE = 'zzz-stale'

_INCLUDE = timedelta(minutes=10)


def _make_payload(session_id: str, cwd: str) -> dict:
    return {
        'session_id': session_id,
        'cwd': cwd,
        'model': {'id': 'claude-sonnet-4-6', 'display_name': 'Claude Sonnet'},
        'cost': {'total_cost_usd': 0.10},
        'rate_limits': {
            'five_hour':  {'used_percentage': 10},
            'seven_day':  {'used_percentage': 20},
        },
    }


def _write_session(
    projects_root: Path,
    payload_root: Path,
    session_id: str,
    cwd: str,
    age_seconds: float,
    now: datetime,
) -> None:
    """Write a .jsonl file and a payload .json file for one session."""
    # jsonl lives one level deep: projects_root/<subdir>/<session_id>.jsonl
    subdir = projects_root / 'my-project'
    subdir.mkdir(parents=True, exist_ok=True)
    jsonl = subdir / f'{session_id}.jsonl'
    jsonl.write_text('')
    ts = now.timestamp() - age_seconds
    os.utime(jsonl, (ts, ts))

    payload = _make_payload(session_id, cwd)
    payload_file = payload_root / f'statusline.{int(now.timestamp())}.{session_id}.json'
    payload_file.write_text(json.dumps(payload))


def test_integration_two_active_one_stale(tmp_path: Path) -> None:
    """Build a synthetic ~/.claude with 2 active + 1 stale session and run the
    discovery → lifecycle → layout pipeline, asserting:
    - only the 2 active session_ids appear in the result
    - they are in alphabetical (cwd) order
    - format_header reports '2 sessions'
    """
    now = datetime.now()

    projects_root = tmp_path / '.claude' / 'projects'
    payload_root  = tmp_path / '.claude' / 'statusline-output'
    projects_root.mkdir(parents=True)
    payload_root.mkdir(parents=True)

    _write_session(projects_root, payload_root, _SESSION_A,     '/home/user/alpha', 120,  now)
    _write_session(projects_root, payload_root, _SESSION_B,     '/home/user/beta',   60,  now)
    _write_session(projects_root, payload_root, _SESSION_STALE, '/home/user/stale', 3600, now)

    # Pass explicit paths so default-argument evaluation doesn't matter.
    from claude.mon.discovery import find_active_jsonls, index_payloads_by_session, ActiveSession

    active_jsonls   = find_active_jsonls(_INCLUDE, now, projects_root=projects_root)
    payload_index   = index_payloads_by_session(payloads_root=payload_root)

    sessions: list[ActiveSession] = []
    for jsonl_path, jsonl_mtime in active_jsonls:
        sid   = jsonl_path.stem
        entry = payload_index.get(sid)
        if entry is None:
            continue
        payload_path, payload_mtime, payload = entry
        sessions.append(ActiveSession(
            session_id=sid,
            jsonl_path=jsonl_path,
            jsonl_mtime=jsonl_mtime,
            payload=payload,
            payload_mtime=payload_mtime,
        ))

    sessions.sort(key=lambda s: (s.payload.get('cwd', ''), s.session_id))

    # --- assertions: active sessions only ---
    session_ids = [s.session_id for s in sessions]
    assert len(sessions) == 2, f'expected 2 active sessions, got {session_ids}'
    assert _SESSION_A     in session_ids
    assert _SESSION_B     in session_ids
    assert _SESSION_STALE not in session_ids

    # --- alphabetical order: alpha before beta ---
    assert sessions[0].payload.get('cwd') == '/home/user/alpha'
    assert sessions[1].payload.get('cwd') == '/home/user/beta'

    # --- lifecycle: both active sessions are bright ---
    idle_after   = timedelta(minutes=2)
    remove_after = timedelta(minutes=15)
    now_ts = now.timestamp()
    for s in sessions:
        tier = classify(s.jsonl_mtime, now_ts, idle_after, remove_after)
        assert tier == 'bright', f'session {s.session_id} expected bright, got {tier}'

    # --- header reports 2 sessions ---
    five_h, seven_d = aggregate_rate_limits(sessions)
    day_cost        = aggregate_day_cost(sessions)
    header          = format_header(len(sessions), five_h, seven_d, day_cost, 120)

    # Strip ANSI escapes for plain-text assertion.
    plain_header = re.sub(r'\033\[[0-9;]*m', '', header)
    assert '2 sessions' in plain_header, f'header does not contain "2 sessions": {plain_header!r}'
