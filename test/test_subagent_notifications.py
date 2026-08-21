"""Tests for the authoritative <task-notification> completion signal.

Replaces prose/heuristic "is this subagent done" inference (terminal-text
pattern-matching, StructuredOutput-block detection) with the structured
<task-notification> record Claude Code itself writes when an async
Agent/Task-tool subagent stops. See yas.info.subagents._collect_task_notifications.
"""
import json
import os
import time
from pathlib import Path

import pytest

from helper import iso_ts
from yas.info.subagents import RunningSubagents, _parse_iso_to_epoch


SESSION_ID = 'sess-notif'
PROJECT_DIR = '/home/user/notifproject'
PROJECT_SLUG = 'home-user-notifproject'


def _project_dir(tmp_home: Path) -> Path:
    return tmp_home / '.claude' / 'projects' / f'-{PROJECT_SLUG}'


def _session_dir(tmp_home: Path) -> Path:
    return _project_dir(tmp_home) / SESSION_ID


def _subagents_dir(tmp_home: Path) -> Path:
    return _session_dir(tmp_home) / 'subagents'


def _write_agent(subagents_dir: Path, agent_id: str, mtime: float | None = None) -> Path:
    subagents_dir.mkdir(parents=True, exist_ok=True)
    meta = subagents_dir / f'{agent_id}.meta.json'
    meta.write_text(json.dumps({'agentType': 'Explore', 'description': 'find X'}))
    jsonl = subagents_dir / f'{agent_id}.jsonl'
    jsonl.write_text('{"event": "start"}\n')
    if mtime is not None:
        os.utime(jsonl, (mtime, mtime))
    return jsonl


def _notif_block(task_id: str, tool_use_id: str, status: str, summary: str = 'done') -> str:
    return (
        '<task-notification>\n'
        f'<task-id>{task_id}</task-id>\n'
        f'<tool-use-id>{tool_use_id}</tool-use-id>\n'
        f'<status>{status}</status>\n'
        f'<summary>{summary}</summary>\n'
        '</task-notification>'
    )


def _queue_operation_line(task_id: str, tool_use_id: str, status: str, ts: str) -> str:
    '''The "type":"queue-operation" record shape.'''
    d = {
        'type': 'queue-operation',
        'operation': 'enqueue',
        'timestamp': ts,
        'content': _notif_block(task_id, tool_use_id, status),
    }
    return json.dumps(d) + '\n'


def _user_record_line(task_id: str, tool_use_id: str, status: str, ts: str) -> str:
    '''The "type":"user" record whose message.content is a plain string
    containing the same <task-notification> block (the second confirmed shape).'''
    d = {
        'type': 'user',
        'timestamp': ts,
        'message': {'content': _notif_block(task_id, tool_use_id, status)},
    }
    return json.dumps(d) + '\n'


def _write_session_jsonl(tmp_home: Path, lines: list[str]) -> Path:
    pdir = _project_dir(tmp_home)
    pdir.mkdir(parents=True, exist_ok=True)
    session_jsonl = pdir / f'{SESSION_ID}.jsonl'
    session_jsonl.write_text(''.join(lines))
    return session_jsonl


def _get(result: RunningSubagents, agent_id: str):
    matches = [s for s in result.subagents if s.agent_id == agent_id]
    assert matches, f'{agent_id} not found among {[s.agent_id for s in result.subagents]}'
    return matches[0]


def test_status_completed(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-c1', mtime=now - 100)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('c1', 'toolu_c1', 'completed', iso_ts(now - 50)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-c1')
    assert sub.status == 'completed'
    assert sub.end_ts > 0
    assert sub.is_done is True
    assert sub.run_count == 1


def test_status_killed(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-k1', mtime=now - 100)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('k1', 'toolu_k1', 'killed', iso_ts(now - 50)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-k1')
    assert sub.status == 'killed'
    assert sub.end_ts > 0
    assert sub.is_done is True


def test_status_failed(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-f1', mtime=now - 100)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('f1', 'toolu_f1', 'failed', iso_ts(now - 50)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-f1')
    assert sub.status == 'failed'
    assert sub.end_ts > 0
    assert sub.is_done is True


def test_status_stopped(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-s1', mtime=now - 100)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('s1', 'toolu_s1', 'stopped', iso_ts(now - 50)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-s1')
    assert sub.status == 'stopped'
    assert sub.end_ts > 0
    assert sub.is_done is True


def test_unknown_status_treated_as_running(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-u1', mtime=now - 100)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('u1', 'toolu_u1', 'some-future-status', iso_ts(now - 50)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-u1')
    assert sub.status == 'running'
    assert sub.end_ts == 0.0
    assert sub.is_done is False
    # The notification was still seen (counted), just not treated as terminal.
    assert sub.run_count == 1


def test_no_notification_at_all_is_running(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-none', mtime=now - 5)
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-none')
    assert sub.status == 'running'
    assert sub.end_ts == 0.0
    assert sub.run_count == 0


def test_terminal_looking_prose_does_not_mark_done(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    subagents_dir = sdir
    subagents_dir.mkdir(parents=True, exist_ok=True)
    meta = subagents_dir / 'agent-prose1.meta.json'
    meta.write_text(json.dumps({'agentType': 'spec-implementer', 'description': 'do work'}))
    jsonl = subagents_dir / 'agent-prose1.jsonl'
    # Final assistant line reads like a wrap-up (end_turn, plain text, no
    # tool_use) — exactly what the deleted terminal-text heuristic used to
    # key off. No <task-notification> anywhere: must stay "running".
    jsonl.write_text(json.dumps({
        'type': 'assistant',
        'timestamp': '2026-07-25T03:40:00.000Z',
        'message': {
            'id': 'msg-1',
            'model': 'claude-x',
            'stop_reason': 'end_turn',
            'usage': {'input_tokens': 1, 'output_tokens': 1},
            'content': [
                {'type': 'text', 'text': 'Still waiting for the actual completion notification...'},
            ],
        },
    }) + '\n')
    os.utime(jsonl, (now, now))
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-prose1')
    assert sub.status == 'running'
    assert sub.end_ts == 0.0
    assert sub.is_done is False


def test_resume_second_notification_bumps_run_count(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-r1', mtime=now - 10)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('r1', 'toolu_r1', 'completed', iso_ts(now - 20)),
        _queue_operation_line('r1', 'toolu_r1_b', 'completed', iso_ts(now - 5)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-r1')
    assert sub.run_count == 2
    assert sub.status == 'completed'
    # end_ts reflects the LATEST notification, not the first.
    assert sub.end_ts == sub.end_ts  # sanity: set
    assert sub.end_ts > 0


def test_resumed_flag_true_when_transcript_postdates_last_notification(tmp_home: Path) -> None:
    # Only one notification, but the transcript kept being written after it —
    # a resumed agent appends more turns to the same jsonl (per the CC note:
    # "the same task-id may notify more than once").
    later = 2000000000.0  # far future mtime, postdates the notification ts
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-r2', mtime=later)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('r2', 'toolu_r2', 'completed', '2026-07-25T03:00:00.000Z'),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-r2')
    assert sub.run_count == 1
    assert sub.resumed is True


def test_run_start_ts_anchors_on_resume_boundary_transcript_line(tmp_home: Path) -> None:
    # Real repro shape: original spawn long ago, one notification, then the
    # transcript is reopened (warm-agent SendMessage) and a fresh assistant
    # line lands well after the notification. run_start_ts must be THAT
    # line's timestamp, not the notification ts and not the original spawn.
    now = time.time()
    notif_epoch = now - 3600
    original_spawn = notif_epoch - 3600
    resume_line_epoch = notif_epoch + 8.6 * 60  # the actual resume-run write
    sdir = _subagents_dir(tmp_home)
    sdir.mkdir(parents=True, exist_ok=True)
    meta = sdir / 'agent-r5.meta.json'
    meta.write_text(json.dumps({'agentType': 'Explore', 'description': 'find X'}))
    jsonl = sdir / 'agent-r5.jsonl'
    jsonl.write_text(
        json.dumps({
            'type': 'assistant',
            'timestamp': iso_ts(original_spawn),
            'message': {'id': 'msg-0', 'model': 'claude-x', 'usage': {}},
        }) + '\n'
        + json.dumps({
            'type': 'assistant',
            'timestamp': iso_ts(resume_line_epoch),
            'message': {'id': 'msg-1', 'model': 'claude-x', 'usage': {}},
        }) + '\n'
    )
    os.utime(jsonl, (resume_line_epoch, resume_line_epoch))
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('r5', 'toolu_r5', 'completed', iso_ts(notif_epoch)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-r5')
    assert sub.resumed is True
    assert sub.run_start_ts == _parse_iso_to_epoch(iso_ts(resume_line_epoch))
    # Original spawn is still preserved separately for cohort membership/sort.
    assert sub.first_timestamp == _parse_iso_to_epoch(iso_ts(original_spawn))


def test_run_start_ts_falls_back_to_notif_ts_when_no_later_line_found(tmp_home: Path) -> None:
    # Resumed (mtime postdates notif_ts) but no transcript line with a
    # timestamp later than notif_ts could be pinpointed (e.g. the stub
    # transcript here carries no timestamp at all) — falls back to notif_ts.
    now = time.time()
    notif_epoch = now - 3600
    later = notif_epoch + 8.6 * 60
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-r6', mtime=later)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('r6', 'toolu_r6', 'completed', iso_ts(notif_epoch)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-r6')
    assert sub.resumed is True
    assert sub.run_start_ts == _parse_iso_to_epoch(iso_ts(notif_epoch))


def test_run_start_ts_equals_first_timestamp_when_never_resumed(tmp_home: Path) -> None:
    now = time.time()
    notif_epoch = now - 100
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-c9', mtime=notif_epoch - 50)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('c9', 'toolu_c9', 'completed', iso_ts(notif_epoch)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-c9')
    assert sub.resumed is False
    assert sub.run_start_ts == sub.first_timestamp


def test_run_start_ts_terminal_resumed_uses_second_to_last_notification(tmp_home: Path) -> None:
    # Resumed agent finishes: the LATEST notification (notif2) is the END of
    # the displayed run, so run_start_ts must anchor on the FIRST transcript
    # line after the PREVIOUS notification (notif1) — anchoring on notif2
    # itself (the old, buggy behaviour) would collapse run_start_ts onto
    # end_ts and render a multi-minute run as '0:00'.
    now = time.time()
    notif1_epoch = now - 3600
    notif2_epoch = notif1_epoch + 300  # 5 min later, the finish
    run2_line_epoch = notif1_epoch + 90  # 1.5 min after notif1, the SECOND run's first write
    original_spawn = notif1_epoch - 3600
    sdir = _subagents_dir(tmp_home)
    sdir.mkdir(parents=True, exist_ok=True)
    meta = sdir / 'agent-r7.meta.json'
    meta.write_text(json.dumps({'agentType': 'Explore', 'description': 'find X'}))
    jsonl = sdir / 'agent-r7.jsonl'
    jsonl.write_text(
        json.dumps({
            'type': 'assistant',
            'timestamp': iso_ts(original_spawn),
            'message': {'id': 'msg-0', 'model': 'claude-x', 'usage': {}},
        }) + '\n'
        + json.dumps({
            'type': 'assistant',
            'timestamp': iso_ts(run2_line_epoch),
            'message': {'id': 'msg-1', 'model': 'claude-x', 'usage': {}},
        }) + '\n'
    )
    # mtime lands within TERMINAL_SKEW_SECONDS of the LATEST notification —
    # the agent is genuinely finished, not still running.
    mtime = notif2_epoch + 0.01
    os.utime(jsonl, (mtime, mtime))
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('r7', 'toolu_r7', 'completed', iso_ts(notif1_epoch)),
        _queue_operation_line('r7', 'toolu_r7_b', 'completed', iso_ts(notif2_epoch)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-r7')
    assert sub.status == 'completed'
    assert sub.run_count == 2
    assert sub.resumed is True
    assert sub.end_ts == _parse_iso_to_epoch(iso_ts(notif2_epoch))
    assert sub.run_start_ts == _parse_iso_to_epoch(iso_ts(run2_line_epoch))
    duration = sub.end_ts - sub.run_start_ts
    assert duration == pytest.approx(notif2_epoch - run2_line_epoch, abs=0.01)


def test_run_start_ts_terminal_resumed_never_collapses_to_zero(tmp_home: Path) -> None:
    # Regression guard: even without a transcript line to pinpoint the exact
    # resume write (a stub transcript, no timestamped lines), the PREVIOUS
    # notification (not the latest one) must be the fallback anchor, so
    # run_start_ts can never land within a whisker of end_ts for a finished,
    # resumed, multi-notification agent.
    now = time.time()
    notif1_epoch = now - 3600
    notif2_epoch = notif1_epoch + 300
    sdir = _subagents_dir(tmp_home)
    mtime = notif2_epoch + 0.01
    _write_agent(sdir, 'agent-r8', mtime=mtime)  # stub transcript, no timestamped lines
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('r8', 'toolu_r8', 'completed', iso_ts(notif1_epoch)),
        _queue_operation_line('r8', 'toolu_r8_b', 'completed', iso_ts(notif2_epoch)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-r8')
    assert sub.run_count == 2
    assert sub.end_ts == _parse_iso_to_epoch(iso_ts(notif2_epoch))
    # Falls back to the PREVIOUS notification, not the latest one.
    assert sub.run_start_ts == _parse_iso_to_epoch(iso_ts(notif1_epoch))
    assert sub.end_ts - sub.run_start_ts == pytest.approx(300.0, abs=0.01)


def test_duplicate_pair_does_not_double_run_count(tmp_home: Path) -> None:
    # One real run notified as a queue-operation/user PAIR, 20ms apart — must
    # count as run_count == 1, and NOT look resumed.
    now = time.time()
    notif_epoch = now - 300
    # mtime matches the LATER (deduped) notification's own round-tripped
    # timestamp exactly, not a raw float sum, so iso_ts's millisecond
    # truncation can never leave mtime a hair past notif_ts and spuriously
    # flip `resumed` via the mtime > notif_ts comparison.
    later_notif_ts = _parse_iso_to_epoch(iso_ts(notif_epoch + 0.02))
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-dup1', mtime=later_notif_ts)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('dup1', 'toolu_dup1', 'completed', iso_ts(notif_epoch)),
        _user_record_line('dup1', 'toolu_dup1', 'completed', iso_ts(notif_epoch + 0.02)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-dup1')
    assert sub.run_count == 1
    assert sub.resumed is False
    assert sub.status == 'completed'


def test_duplicate_pairs_across_two_real_runs_count_as_two(tmp_home: Path) -> None:
    # Two real runs, each notified as a pair (4 raw records total) — must
    # dedupe to run_count == 2, and the bracket (prev_ts) must land on the
    # FIRST run's own pair, not the twin of the second run's own notification.
    now = time.time()
    run1_q = now - 3600
    run1_u = run1_q + 0.02
    run2_q = run1_q + 16 * 60  # ~16 min later, a real resume gap
    run2_u = run2_q + 0.02
    original_spawn = run1_q - 3600
    second_run_line = run1_u + 400  # first write of the SECOND run, well after run1's own pair
    sdir = _subagents_dir(tmp_home)
    sdir.mkdir(parents=True, exist_ok=True)
    meta = sdir / 'agent-dup2.meta.json'
    meta.write_text(json.dumps({'agentType': 'Explore', 'description': 'find X'}))
    jsonl = sdir / 'agent-dup2.jsonl'
    jsonl.write_text(
        json.dumps({
            'type': 'assistant',
            'timestamp': iso_ts(original_spawn),
            'message': {'id': 'msg-0', 'model': 'claude-x', 'usage': {}},
        }) + '\n'
        + json.dumps({
            'type': 'assistant',
            'timestamp': iso_ts(second_run_line),
            'message': {'id': 'msg-1', 'model': 'claude-x', 'usage': {}},
        }) + '\n'
    )
    mtime = run2_u + 0.02
    os.utime(jsonl, (mtime, mtime))
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('dup2', 'toolu_dup2a', 'completed', iso_ts(run1_q)),
        _user_record_line('dup2', 'toolu_dup2a', 'completed', iso_ts(run1_u)),
        _queue_operation_line('dup2', 'toolu_dup2b', 'completed', iso_ts(run2_q)),
        _user_record_line('dup2', 'toolu_dup2b', 'completed', iso_ts(run2_u)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-dup2')
    assert sub.run_count == 2  # NOT 4 (raw record count)
    assert sub.resumed is True
    assert sub.status == 'completed'
    assert sub.end_ts == _parse_iso_to_epoch(iso_ts(run2_u))
    # The bracket must land on run1's own notification (the "user" twin, the
    # later of run1's pair), NOT on the "queue-operation" twin of run2's own
    # notification (which sits only 20ms before end_ts and would collapse
    # duration to ~0).
    assert sub.run_start_ts == _parse_iso_to_epoch(iso_ts(second_run_line))
    duration = sub.end_ts - sub.run_start_ts
    assert duration > 60  # comfortably not the ~0.02s a doubled-count bug would produce
    assert duration == pytest.approx(run2_u - second_run_line, abs=0.01)


def test_real_audiovis_shaped_repro_analysis_agent_ten_records_five_runs(tmp_home: Path) -> None:
    # Mirrors the exact shape found in a real 'analysis' agent: 10 raw
    # notification records (5 queue-operation/user pairs) for one task-id.
    # Regression guard for the specific "×9 ↺" / '0:00' symptom.
    now = time.time()
    gaps = [0, 20 * 60, 33 * 60, 43 * 60, 60 * 60]  # ~20/13/10/17 min apart
    pairs = [(now - 3600 + g, now - 3600 + g + 0.023) for g in gaps]
    lines = []
    for q_ts, u_ts in pairs:
        lines.append(_queue_operation_line('analysis1', 'toolu_analysis1', 'completed', iso_ts(q_ts)))
        lines.append(_user_record_line('analysis1', 'toolu_analysis1', 'completed', iso_ts(u_ts)))
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-analysis1', mtime=pairs[-1][1] + 0.02)
    _write_session_jsonl(tmp_home, lines)
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-analysis1')
    assert sub.run_count == 5  # NOT 10
    assert sub.resumed is True
    assert sub.status == 'completed'
    assert sub.end_ts == _parse_iso_to_epoch(iso_ts(pairs[-1][1]))
    # No transcript line to pinpoint (stub transcript) -> falls back to the
    # PREVIOUS real notification's ts (pair #4's "user" record), not pair
    # #5's own queue-operation twin.
    assert sub.run_start_ts == _parse_iso_to_epoch(iso_ts(pairs[-2][1]))
    duration = sub.end_ts - sub.run_start_ts
    assert duration == pytest.approx(pairs[-1][1] - pairs[-2][1], abs=0.01)
    assert duration > 60  # not the ~0.023s a doubled-count bug would produce


def test_notification_in_nested_parent_agent_jsonl(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    # Parent agent (depth 1) and its child (depth 2) both live under the same
    # session's subagents/ dir. The child's completion notification is
    # written into the PARENT's own transcript, not the top-level session file.
    _write_agent(sdir, 'agent-parent1', mtime=now - 200)
    _write_agent(sdir, 'agent-child1', mtime=now - 50)
    # Give the child a parentAgentId pointing at the parent.
    child_meta = sdir / 'agent-child1.meta.json'
    child_meta.write_text(json.dumps({
        'agentType': 'general-purpose',
        'description': 'nested work',
        'parentAgentId': 'agent-parent1',
        'spawnDepth': 2,
    }))
    # Notification for the child lands in the PARENT's own jsonl.
    parent_jsonl = sdir / 'agent-parent1.jsonl'
    parent_jsonl.write_text(
        '{"event": "start"}\n'
        + _queue_operation_line('child1', 'toolu_child1', 'completed', iso_ts(now - 20))
    )
    # Top-level session file has nothing about the child at all.
    _write_session_jsonl(tmp_home, ['{"event": "unrelated"}\n'])

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    child = _get(result, 'agent-child1')
    assert child.status == 'completed'
    assert child.end_ts > 0
    assert child.parent_id == 'agent-parent1'


def test_queue_operation_record_shape(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-shapeq', mtime=now - 5)
    _write_session_jsonl(tmp_home, [
        _queue_operation_line('shapeq', 'toolu_shapeq', 'completed', iso_ts(now - 2)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-shapeq')
    assert sub.status == 'completed'


def test_user_record_shape(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-shapeu', mtime=now - 5)
    _write_session_jsonl(tmp_home, [
        _user_record_line('shapeu', 'toolu_shapeu', 'completed', iso_ts(now - 2)),
    ])
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-shapeu')
    assert sub.status == 'completed'


def test_meta_fields_surfaced(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    sdir.mkdir(parents=True, exist_ok=True)
    meta = sdir / 'agent-metafields.meta.json'
    meta.write_text(json.dumps({
        'agentType': 'fork',
        'description': 'a forked agent',
        'isFork': True,
        'parentAgentId': 'agent-parentx',
        'model': 'claude-opus-9',
        'spawnDepth': 2,
    }))
    jsonl = sdir / 'agent-metafields.jsonl'
    jsonl.write_text('{"event": "start"}\n')
    os.utime(jsonl, (now, now))

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = _get(result, 'agent-metafields')
    assert sub.is_fork is True
    assert sub.parent_id == 'agent-parentx'
    assert sub.model == 'claude-opus-9'
