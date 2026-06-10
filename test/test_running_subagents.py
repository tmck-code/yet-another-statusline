"""Tests for RunningSubagents.from_session."""
import json
import os
import time
from pathlib import Path


from yas.info.subagents import RunningSubagents


SESSION_ID = 'sess-abc'
PROJECT_DIR = '/home/user/myproject'
# slug: '/home/user/myproject' → '-home-user-myproject' → 'home-user-myproject'
PROJECT_SLUG = 'home-user-myproject'


def _subagents_dir(tmp_home: Path) -> Path:
    return tmp_home / '.claude' / 'projects' / f'-{PROJECT_SLUG}' / SESSION_ID / 'subagents'


def _write_agent(
    subagents_dir: Path,
    agent_id: str,
    agent_type: str = 'Explore',
    description: str = 'find X',
    jsonl_lines: list[str] | None = None,
    mtime: float | None = None,
) -> tuple[Path, Path]:
    subagents_dir.mkdir(parents=True, exist_ok=True)
    meta = subagents_dir / f'{agent_id}.meta.json'
    meta.write_text(json.dumps({'agentType': agent_type, 'description': description}))
    jsonl = subagents_dir / f'{agent_id}.jsonl'
    lines = jsonl_lines if jsonl_lines is not None else ['{"event": "start"}\n']
    jsonl.write_text(''.join(lines))
    if mtime is not None:
        os.utime(jsonl, (mtime, mtime))
    return meta, jsonl


def _assistant_line(
    msg_id: str,
    *,
    input_tokens: int       = 0,
    cache_creation: int     = 0,
    cache_read: int         = 0,
    output_tokens: int      = 0,
    timestamp: str | None   = None,
    model: str | None       = None,
    content: list | None    = None,
) -> str:
    d: dict = {
        'type': 'assistant',
        'message': {
            'id': msg_id,
            'usage': {
                'input_tokens': input_tokens,
                'cache_creation_input_tokens': cache_creation,
                'cache_read_input_tokens': cache_read,
                'output_tokens': output_tokens,
            },
        },
    }
    if timestamp:
        d['timestamp'] = timestamp
    if model is not None:
        d['message']['model'] = model
    if content is not None:
        d['message']['content'] = content
    return json.dumps(d) + '\n'


def test_missing_directory_returns_empty(tmp_home: Path) -> None:
    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    assert result == RunningSubagents(subagents=[])


def test_fresh_entry_included(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-1', agent_type='Explore', description='find X', mtime=now)

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    assert len(result.subagents) == 1
    sub = result.subagents[0]
    assert sub.agent_type  == 'Explore'
    assert sub.description == 'find X'


def test_stale_entry_included_in_from_session(tmp_home: Path) -> None:
    # from_session no longer drops stale agents — stale-filtering is delegated
    # to RunningSubagents.visible(), so from_session returns every agent found
    # on disk regardless of mtime age.
    now = time.time()
    stale_mtime = now - RunningSubagents.STALE_SECONDS - 1
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-stale', mtime=stale_mtime)

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    assert len(result.subagents) == 1
    assert result.subagents[0].mtime == stale_mtime


def test_stale_seconds_is_alias_for_liveness_window() -> None:
    # STALE_SECONDS is kept for backward compat; it aliases LIVENESS_WINDOW_SECONDS (30 s)
    assert RunningSubagents.STALE_SECONDS == RunningSubagents.LIVENESS_WINDOW_SECONDS


def test_project_dir_with_leading_slash_produces_correct_slug(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-2', mtime=now)

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    assert len(result.subagents) == 1


def test_token_totals_sum_across_assistant_entries(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-tok',
        jsonl_lines=[
            _assistant_line('m1', input_tokens=6, cache_creation=14052, output_tokens=4, timestamp='2026-05-22T17:38:31.005Z'),
            _assistant_line('m2', input_tokens=1, cache_creation=2824,  output_tokens=1528),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.billed_in == 6 + 14052 + 1 + 2824
    assert sub.output    == 4 + 1528


def test_duplicate_message_id_deduped(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-dup',
        jsonl_lines=[
            _assistant_line('m1', input_tokens=10, output_tokens=20),
            _assistant_line('m1', input_tokens=10, output_tokens=20),  # duplicate id, should be skipped
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.billed_in == 10
    assert sub.output    == 20


def test_first_timestamp_extracted(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-ts',
        jsonl_lines=[
            '{"event": "start"}\n',  # no timestamp
            _assistant_line('m1', timestamp='2026-05-22T17:38:31.005Z'),
            _assistant_line('m2', timestamp='2026-05-22T17:38:54.652Z'),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    # First timestamp wins (2026-05-22T17:38:31Z)
    assert sub.first_timestamp > 0
    # Spot check: epoch for 2026-05-22 17:38:31 UTC ≈ 1779471511
    assert 1779471510 < sub.first_timestamp < 1779471512


def test_subagents_sorted_by_first_timestamp_ascending(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-late',  jsonl_lines=[_assistant_line('a', timestamp='2026-05-22T18:00:00Z')], mtime=now)
    _write_agent(sdir, 'agent-early', jsonl_lines=[_assistant_line('b', timestamp='2026-05-22T17:00:00Z')], mtime=now)

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    assert [s.first_timestamp for s in result.subagents] == sorted(s.first_timestamp for s in result.subagents)


def test_fresh_entry_with_model_and_live_fields(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-rich',
        jsonl_lines=[
            _assistant_line(
                'm1',
                input_tokens=100,
                cache_creation=50,
                cache_read=200,
                output_tokens=80,
                model='claude-sonnet-4-6',
                content=[{'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'pytest'}}],
            ),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.model         == 'claude-sonnet-4-6'
    assert sub.billed_in     == 150   # input_tokens + cache_creation
    assert sub.cache_read_in == 200
    assert sub.output        == 80
    assert sub.total_input   == 350   # billed_in + cache_read_in
    assert sub.last_activity == ('tool_use', 'Bash', {'command': 'pytest'})


def test_last_activity_text_after_tool_use(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-text',
        jsonl_lines=[
            _assistant_line(
                'm1',
                output_tokens=10,
                content=[
                    {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': '/x.py', 'old_string': 'a', 'new_string': 'b'}},
                    {'type': 'text', 'text': 'done'},
                ],
            ),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    # A trailing text block must not mask a real tool_use earlier in the
    # message: the last tool_use wins (Claude often emits [tool_use, text]).
    assert sub.last_activity == ('tool_use', 'Edit', {'file_path': '/x.py', 'old_string': 'a', 'new_string': 'b'})


def test_last_activity_thinking_only(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-think',
        jsonl_lines=[
            _assistant_line(
                'm1',
                output_tokens=5,
                content=[{'type': 'thinking', 'thinking': 'considering...'}],
            ),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.last_activity == ('thinking', '', {})


def _assistant_line_with_stop_reason(
    msg_id: str,
    stop_reason: str,
    *,
    timestamp: str | None = None,
    output_tokens: int    = 1,
) -> str:
    d: dict = {
        'type': 'assistant',
        'message': {
            'id': msg_id,
            'stop_reason': stop_reason,
            'usage': {
                'input_tokens': 0,
                'cache_creation_input_tokens': 0,
                'cache_read_input_tokens': 0,
                'output_tokens': output_tokens,
            },
        },
    }
    if timestamp:
        d['timestamp'] = timestamp
    return json.dumps(d) + '\n'


def test_end_ts_set_when_end_turn_present(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    end_turn_ts = '2026-05-22T18:00:00.000Z'
    _write_agent(
        sdir, 'agent-done',
        jsonl_lines=[
            _assistant_line('m1', input_tokens=10, output_tokens=5, timestamp='2026-05-22T17:50:00.000Z'),
            _assistant_line_with_stop_reason('m2', 'end_turn', timestamp=end_turn_ts, output_tokens=3),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts > 0
    # 2026-05-22T18:00:00Z → epoch ≈ 1779472800
    assert 1779472799 < sub.end_ts < 1779472801


def _assistant_line_full(
    msg_id: str,
    stop_reason: str | None,
    *,
    input_tokens: int   = 0,
    cache_creation: int = 0,
    cache_read: int     = 0,
    output_tokens: int  = 0,
    timestamp: str | None = None,
    model: str | None     = None,
    content: list | None  = None,
) -> str:
    '''Assistant+usage line with an explicit stop_reason (which may be null).

    Mirrors the streaming transcript shape the production parser reads: the same
    message.id is written first as a partial (stop_reason: null) then again as a
    final write (stop_reason: "end_turn"), with identical usage numbers.
    '''
    d: dict = {
        'type': 'assistant',
        'message': {
            'id': msg_id,
            'stop_reason': stop_reason,
            'usage': {
                'input_tokens': input_tokens,
                'cache_creation_input_tokens': cache_creation,
                'cache_read_input_tokens': cache_read,
                'output_tokens': output_tokens,
            },
        },
    }
    if timestamp:
        d['timestamp'] = timestamp
    if model is not None:
        d['message']['model'] = model
    if content is not None:
        d['message']['content'] = content
    return json.dumps(d) + '\n'


def test_end_turn_detected_when_id_shared_with_earlier_partial(tmp_home: Path) -> None:
    # Regression (2.1): streaming writes the same message.id twice — an early
    # partial with stop_reason: null, then a final write with end_turn. The
    # message-id dedup must NOT suppress the terminal-state capture on the final
    # write; before the fix end_ts stayed 0 and the agent looked active forever.
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    end_turn_ts = '2026-05-22T18:00:00.000Z'
    _write_agent(
        sdir, 'agent-streamed-done',
        jsonl_lines=[
            # early partial: same id, stop_reason null, not yet terminal
            _assistant_line_full('m1', None, input_tokens=10, output_tokens=5, timestamp='2026-05-22T17:59:59.000Z'),
            # final write: SAME id, now end_turn — dedup must not skip end_ts capture
            _assistant_line_full('m1', 'end_turn', input_tokens=10, output_tokens=5, timestamp=end_turn_ts),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts > 0
    # 2026-05-22T18:00:00Z → epoch ≈ 1779472800
    assert 1779472799 < sub.end_ts < 1779472801


def test_shared_id_usage_counted_exactly_once(tmp_home: Path) -> None:
    # 2.2: the partial and the final write share message.id AND usage numbers;
    # token accumulation stays behind the dedup guard, so tokens must be counted
    # exactly once (no double-count from the two writes of the same message).
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-streamed-tokens',
        jsonl_lines=[
            _assistant_line_full('m1', None,       input_tokens=10, cache_creation=7, output_tokens=20, timestamp='2026-05-22T17:59:59.000Z'),
            _assistant_line_full('m1', 'end_turn', input_tokens=10, cache_creation=7, output_tokens=20, timestamp='2026-05-22T18:00:00.000Z'),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    # Counted once: a single message's billed_in (input + cache_creation) and output.
    assert sub.billed_in == 17
    assert sub.output    == 20
    # And the agent is still detected as Done.
    assert sub.end_ts > 0


def test_end_ts_zero_when_no_end_turn(tmp_home: Path) -> None:
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-running',
        jsonl_lines=[
            _assistant_line('m1', input_tokens=10, output_tokens=5, timestamp='2026-05-22T17:50:00.000Z'),
            _assistant_line('m2', input_tokens=5,  output_tokens=2, timestamp='2026-05-22T17:55:00.000Z'),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts == 0.0
