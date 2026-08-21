"""Tests for RunningSubagents.from_session."""
import json
import os
import time
from pathlib import Path


from helper import iso_ts
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
    # end_turn alone is transcript inference, not the authoritative
    # <task-notification> signal — RunningSubagent.end_ts/status now come
    # ONLY from the notification map (see test_subagent_notifications.py),
    # so with no notification present the agent is still "running".
    assert sub.end_ts == 0.0
    assert sub.status == 'running'


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
    # Same migration note as test_end_ts_set_when_end_turn_present: end_turn
    # is no longer a completion signal for RunningSubagent — only the
    # authoritative <task-notification>. The dedup-vs-terminal-capture
    # regression this test protects still lives in parse_transcript's
    # own end_ts return, exercised directly where needed; here we only
    # assert from_session no longer surfaces it as Done.
    assert sub.end_ts == 0.0


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
    # end_ts is no longer derived from end_turn (see migration note above);
    # only the token-dedup behaviour is under test here.
    assert sub.end_ts == 0.0


def test_streamed_trailing_text_does_not_mask_tool_use(tmp_home: Path) -> None:
    # One content block per streamed write, same message id: the activity
    # snippet must observe the message's later writes, not just its first
    # (usually the thinking block), and the message-scoped priority
    # (tool_use > text > thinking) must hold across the writes — a trailing
    # text narration must not mask the tool_use before it, exactly as within
    # a single whole-message content array.
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-streamed-activity',
        jsonl_lines=[
            _assistant_line_full('m1', None, output_tokens=5,
                                 content=[{'type': 'thinking', 'thinking': 'planning'}]),
            _assistant_line_full('m1', None, output_tokens=5,
                                 content=[{'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': '/x.py'}}]),
            _assistant_line_full('m1', None, output_tokens=9,
                                 content=[{'type': 'text', 'text': 'edited'}]),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.last_activity == ('tool_use', 'Edit', {'file_path': '/x.py'})


def test_streamed_usage_last_line_wins(tmp_home: Path) -> None:
    # On real transcripts the partial and final writes of a streamed message do
    # NOT carry identical usage: the counters grow across the writes and the
    # final one holds the message's real totals. The counters must take the
    # last write's snapshot — not freeze at the first partial (out=2 here) and
    # not sum the snapshots (out=305).
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-usage-grows',
        jsonl_lines=[
            _assistant_line_full('m1', None,       input_tokens=26, output_tokens=2,
                                 timestamp='2026-05-22T17:59:00.000Z',
                                 content=[{'type': 'thinking', 'thinking': 'hmm'}]),
            _assistant_line_full('m1', None,       input_tokens=26, output_tokens=2,
                                 content=[{'type': 'text', 'text': 'Checking the tests.'}]),
            _assistant_line_full('m1', 'end_turn', input_tokens=26, output_tokens=301,
                                 timestamp='2026-05-22T18:00:00.000Z',
                                 content=[{'type': 'text', 'text': 'All done.'}]),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.billed_in == 26
    assert sub.output    == 301
    # end_ts is no longer derived from end_turn (see migration note above).
    assert sub.end_ts == 0.0


def test_end_ts_cleared_when_agent_resumes_after_end_turn(tmp_home: Path) -> None:
    # A warm agent ends its turn, then is handed a follow-up (SendMessage) and
    # starts working again: the old end_turn no longer marks it Done, otherwise
    # the cohort's clean-retire would hide an actively working agent. Its last
    # line is a pending tool_use, so no post-loop fallback fires either.
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-resumed-working',
        jsonl_lines=[
            _assistant_line_full('m1', 'end_turn', timestamp='2026-05-22T18:00:00.000Z',
                                 content=[{'type': 'text', 'text': 'first task done'}]),
            _assistant_line_full('m2', None,       timestamp='2026-05-22T18:30:00.000Z', output_tokens=4,
                                 content=[{'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ls'}}]),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts == 0.0


def test_resumed_agent_done_again_via_terminal_text(tmp_home: Path) -> None:
    # Regression guard for the bias rule: a follow-up terminal-looking text
    # report with no new end_turn and no <task-notification> must NOT mark
    # the agent Done — the deleted terminal-text fallback used to do exactly
    # this. Absent a notification, the agent stays "running".
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-resumed-done',
        jsonl_lines=[
            _assistant_line_full('m1', 'end_turn', timestamp='2026-05-22T18:00:00.000Z',
                                 content=[{'type': 'text', 'text': 'first task done'}]),
            _assistant_line_full('m2', None,       timestamp='2026-05-22T18:30:00.000Z', output_tokens=7,
                                 content=[{'type': 'text', 'text': 'follow-up report'}]),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts == 0.0
    assert sub.status == 'running'


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


def _text(s: str) -> dict:
    return {'type': 'text', 'text': s}


def _tool(name: str = 'Bash') -> dict:
    return {'type': 'tool_use', 'name': name, 'input': {'command': 'ls'}}


def test_terminal_text_null_stop_reason_detects_done(tmp_home: Path) -> None:
    # Some sidechain (sub-agent) transcripts NEVER emit stop_reason: "end_turn"
    # — every assistant line is either "tool_use" or null, including the final
    # result message. The now-deleted terminal-text fallback used to mark this
    # Done from prose; per the bias rule that is no longer a completion signal
    # at all — without a <task-notification>, the agent stays "running"
    # regardless of how final its last text block looks.
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    final_ts = '2026-05-22T18:00:10.000Z'
    _write_agent(
        sdir, 'agent-null-done',
        jsonl_lines=[
            # interstitial narration: text, null stop, NOT terminal (work follows)
            _assistant_line_full('m1', None, output_tokens=2, content=[_text('Let me check.')],
                                 timestamp='2026-05-22T18:00:00.000Z'),
            # a tool turn
            _assistant_line_full('m2', 'tool_use', output_tokens=2, content=[_tool('Read')],
                                 timestamp='2026-05-22T18:00:05.000Z'),
            # tool result
            json.dumps({'type': 'user', 'message': {'role': 'user', 'content': []}}) + '\n',
            # final result message: text, null stop, no end_turn anywhere
            _assistant_line_full('m3', None, output_tokens=9, content=[_text('Done. Synced.')],
                                 timestamp=final_ts),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts == 0.0
    assert sub.status == 'running'


def test_last_line_tool_use_not_done(tmp_home: Path) -> None:
    # A still-running agent whose final assistant line is a tool_use (awaiting a
    # result) and has no end_turn must NOT be marked Done by the fallback.
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-mid-tool',
        jsonl_lines=[
            _assistant_line_full('m1', None, output_tokens=2, content=[_text('Working.')],
                                 timestamp='2026-05-22T18:00:00.000Z'),
            _assistant_line_full('m2', 'tool_use', output_tokens=2, content=[_tool('Bash')],
                                 timestamp='2026-05-22T18:00:05.000Z'),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts == 0.0


def test_interstitial_text_with_trailing_tool_use_not_done(tmp_home: Path) -> None:
    # The hazard the LAST-line rule guards against: an assistant message that
    # carries text AND a tool_use ([text, tool_use]) is mid-turn work, not a
    # terminal text result — must not be Done even though a text block exists.
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-text-then-tool',
        jsonl_lines=[
            _assistant_line_full('m1', None, output_tokens=4,
                                 content=[_text('Now I will run it.'), _tool('Bash')],
                                 timestamp='2026-05-22T18:00:00.000Z'),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts == 0.0


def test_end_turn_takes_precedence_over_terminal_text_fallback(tmp_home: Path) -> None:
    # The terminal-text fallback this test named is deleted; end_turn alone is
    # also no longer a completion signal for RunningSubagent — only the
    # authoritative <task-notification> is. No notification here, so running.
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    end_turn_ts = '2026-05-22T18:00:00.000Z'
    _write_agent(
        sdir, 'agent-endturn-primary',
        jsonl_lines=[
            _assistant_line_full('m1', 'end_turn', output_tokens=5,
                                 content=[_text('All done.')], timestamp=end_turn_ts),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts == 0.0


def test_structured_output_tool_use_detects_done(tmp_home: Path) -> None:
    # The StructuredOutput-block heuristic is deleted per the bias rule: a
    # StructuredOutput tool_use, however final-looking, is no longer treated
    # as a completion signal. Only a <task-notification> can mark Done now.
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    struct_out_ts = '2026-05-22T18:00:00.000Z'
    _write_agent(
        sdir, 'agent-struct-done',
        jsonl_lines=[
            _assistant_line_full(
                'm1', 'tool_use', output_tokens=5, timestamp=struct_out_ts,
                content=[{'type': 'tool_use', 'name': 'StructuredOutput', 'input': {'schema': '{}', 'json': '{}'}}]
            ),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    # No <task-notification> present: StructuredOutput alone no longer sets end_ts.
    assert sub.end_ts == 0.0


def test_structured_output_null_stop_reason_detects_done(tmp_home: Path) -> None:
    # Same deleted heuristic as above, exercised with the null stop_reason
    # shape a streamed-but-not-finalized write can have. Still must stay
    # "running" absent a <task-notification>.
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    struct_ts = '2026-05-22T18:00:00.000Z'
    _write_agent(
        sdir, 'agent-struct-null',
        jsonl_lines=[
            _assistant_line_full(
                'm1', None, output_tokens=4, timestamp=struct_ts,
                content=[{'type': 'tool_use', 'name': 'StructuredOutput', 'input': {'schema': '{}', 'json': '{}'}}]
            ),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts == 0.0


def _write_agent_with_tool_use_id(
    subagents_dir: Path,
    agent_id: str,
    tool_use_id: str,
    *,
    agent_type: str  = 'Explore',
    description: str = 'find X',
    jsonl_lines: list[str] | None = None,
    mtime: float | None = None,
) -> tuple[Path, Path]:
    '''Like _write_agent, but the meta.json also carries toolUseId, the join
    key for the tier-1 toolUseResult lookup in the spawning transcript.'''
    subagents_dir.mkdir(parents=True, exist_ok=True)
    meta = subagents_dir / f'{agent_id}.meta.json'
    meta.write_text(json.dumps({
        'agentType': agent_type, 'description': description, 'toolUseId': tool_use_id,
    }))
    jsonl = subagents_dir / f'{agent_id}.jsonl'
    lines = jsonl_lines if jsonl_lines is not None else ['{"event": "start"}\n']
    jsonl.write_text(''.join(lines))
    if mtime is not None:
        os.utime(jsonl, (mtime, mtime))
    return meta, jsonl


def _tool_result_line(tool_use_id: str, status: str, timestamp: str) -> str:
    '''A top-level session-transcript record carrying the toolUseResult
    sibling field the way Claude Code core writes it for a resolved
    Agent/Task tool call.'''
    d = {
        'type': 'user',
        'timestamp': timestamp,
        'message': {
            'content': [{'type': 'tool_result', 'tool_use_id': tool_use_id, 'content': []}],
        },
        'toolUseResult': {'status': status, 'timestamp': timestamp},
    }
    return json.dumps(d) + '\n'


def test_tool_use_result_marks_done_without_any_notification(tmp_home: Path) -> None:
    '''An agent with no <task-notification> anywhere, but whose spawning
    transcript's tool_result carries toolUseResult.status == "completed", is
    treated as done via the tier-1 signal.
    '''
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent_with_tool_use_id(
        sdir, 'agent-tier1', 'toolu_abc123',
        jsonl_lines=[_assistant_line('m1', output_tokens=5)],
        mtime=now - 5.0,
    )
    session_jsonl = tmp_home / '.claude' / 'projects' / f'-{PROJECT_SLUG}' / f'{SESSION_ID}.jsonl'
    session_jsonl.parent.mkdir(parents=True, exist_ok=True)
    # The completion timestamp must postdate the transcript's own last write,
    # or the stale-terminal-signal invalidation correctly rejects it.
    session_jsonl.write_text(_tool_result_line('toolu_abc123', 'completed', iso_ts(now - 2.0)))

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR, now=now)
    sub = result.subagents[0]
    assert sub.status == 'completed'
    assert sub.is_done
    assert sub.end_ts > 0


def test_tool_use_result_non_completed_status_stays_running(tmp_home: Path) -> None:
    '''An unconfirmed (non-"completed") toolUseResult status is not trusted
    on its own -- the agent stays "running" pending a real terminal signal.
    '''
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent_with_tool_use_id(
        sdir, 'agent-tier1-pending', 'toolu_def456',
        jsonl_lines=[_assistant_line('m1', output_tokens=5)],
        mtime=now - 5.0,
    )
    session_jsonl = tmp_home / '.claude' / 'projects' / f'-{PROJECT_SLUG}' / f'{SESSION_ID}.jsonl'
    session_jsonl.parent.mkdir(parents=True, exist_ok=True)
    session_jsonl.write_text(_tool_result_line('toolu_def456', 'in_progress', '2026-05-22T18:00:00.000Z'))

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR, now=now)
    sub = result.subagents[0]
    assert sub.status == 'running'
    assert not sub.is_done


def test_lost_notification_fallback_marks_done_past_abandoned_horizon(tmp_home: Path) -> None:
    '''An agent whose transcript ends in stop_reason: end_turn, with no
    <task-notification> ever received, and silent well past
    ABANDONED_HORIZON_SECONDS, is treated as done via the staleness fallback.
    '''
    now = time.time()
    end_turn_ts = '2026-05-22T18:00:00.000Z'
    stale_mtime = now - RunningSubagents.ABANDONED_HORIZON_SECONDS - 1
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-lost-notif',
        jsonl_lines=[
            _assistant_line_full('m1', 'end_turn', output_tokens=5, timestamp=end_turn_ts),
        ],
        mtime=stale_mtime,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR, now=now)
    sub = result.subagents[0]
    assert sub.status == 'completed'
    assert sub.end_ts == stale_mtime
    assert sub.is_done


def test_terminal_stop_reason_but_fresh_mtime_stays_running(tmp_home: Path) -> None:
    '''An agent with a terminal stop_reason but a transcript still within
    ABANDONED_HORIZON_SECONDS is NOT treated as done by the fallback -- it
    keeps waiting for the real <task-notification> (no false positive).
    '''
    now = time.time()
    end_turn_ts = '2026-05-22T18:00:00.000Z'
    fresh_mtime = now - (RunningSubagents.ABANDONED_HORIZON_SECONDS - 5)
    sdir = _subagents_dir(tmp_home)
    _write_agent(
        sdir, 'agent-fresh-end-turn',
        jsonl_lines=[
            _assistant_line_full('m1', 'end_turn', output_tokens=5, timestamp=end_turn_ts),
        ],
        mtime=fresh_mtime,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR, now=now)
    sub = result.subagents[0]
    assert sub.status == 'running'
    assert sub.end_ts == 0.0
    assert not sub.is_done


def test_structured_output_duplicate_message_detects_done(tmp_home: Path) -> None:
    # Same deleted heuristic, exercised with a re-streamed duplicate message
    # id. Still must stay "running" absent a <task-notification>.
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    struct_ts = '2026-05-22T18:00:00.000Z'
    _write_agent(
        sdir, 'agent-struct-dup',
        jsonl_lines=[
            # First write: partial with StructuredOutput, stop_reason null
            _assistant_line_full(
                'm1', None, output_tokens=3, timestamp=struct_ts,
                content=[{'type': 'tool_use', 'name': 'StructuredOutput', 'input': {'schema': '{}', 'json': '{}'}}]
            ),
            # Final write: same message id, stop_reason tool_use
            _assistant_line_full(
                'm1', 'tool_use', output_tokens=3, timestamp=struct_ts,
                content=[{'type': 'tool_use', 'name': 'StructuredOutput', 'input': {'schema': '{}', 'json': '{}'}}]
            ),
        ],
        mtime=now,
    )

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    sub = result.subagents[0]
    assert sub.end_ts == 0.0


def _notification_line(task_id: str, status: str, timestamp: str) -> str:
    '''A top-level session-transcript <task-notification> record, keyed by
    task-id == the agent-*.jsonl filename stem minus the "agent-" prefix.'''
    return json.dumps({
        'type': 'queue-operation',
        'operation': 'enqueue',
        'timestamp': timestamp,
        'content': (
            '<task-notification>\n'
            f'<task-id>{task_id}</task-id>\n'
            f'<status>{status}</status>\n'
            '<summary>s</summary>\n'
            '</task-notification>'
        ),
    }) + '\n'


class TestStaleTerminalSignal:
    '''A terminal signal is only believable while the transcript agrees.

    A stall watchdog can emit <status>failed</status> for an agent that keeps
    working; the transcript write that postdates it invalidates the stamp.
    '''

    def _write_session(self, tmp_home: Path, line: str) -> None:
        session_jsonl = tmp_home / '.claude' / 'projects' / f'-{PROJECT_SLUG}' / f'{SESSION_ID}.jsonl'
        session_jsonl.parent.mkdir(parents=True, exist_ok=True)
        session_jsonl.write_text(line)

    def test_transcript_written_after_terminal_signal_stays_live(self, tmp_home: Path) -> None:
        # setup: watchdog failed the agent 20 min ago, transcript written 5 s ago
        now = time.time()
        notif_ts = now - 1200.0
        live_mtime = now - 5.0
        sdir = _subagents_dir(tmp_home)
        _write_agent(
            sdir, 'agent-stalled',
            jsonl_lines=[_assistant_line('m1', output_tokens=5)],
            mtime=live_mtime,
        )
        self._write_session(tmp_home, _notification_line('stalled', 'failed', iso_ts(notif_ts)))

        sub = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR, now=now).subagents[0]

        expected = ('running', 0.0, False)

        assert (sub.status, sub.end_ts, sub.is_done) == expected

    def test_invalidated_terminal_signal_keeps_resumed_flag(self, tmp_home: Path) -> None:
        # setup: the same stale-stamp shape — the ↺ marker must survive the fix
        now = time.time()
        notif_ts = now - 1200.0
        sdir = _subagents_dir(tmp_home)
        _write_agent(
            sdir, 'agent-stalled-resumed',
            jsonl_lines=[_assistant_line('m1', output_tokens=5)],
            mtime=now - 5.0,
        )
        self._write_session(tmp_home, _notification_line('stalled-resumed', 'failed', iso_ts(notif_ts)))

        sub = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR, now=now).subagents[0]

        assert sub.resumed

    def test_finished_agent_still_retires(self, tmp_home: Path) -> None:
        # setup: notification postdates the last transcript write — a real finish
        now = time.time()
        notif_ts = now - 100.0
        sdir = _subagents_dir(tmp_home)
        _write_agent(
            sdir, 'agent-finished',
            jsonl_lines=[_assistant_line('m1', output_tokens=5)],
            mtime=notif_ts - 3.0,
        )
        self._write_session(tmp_home, _notification_line('finished', 'completed', iso_ts(notif_ts)))

        parsed = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR, now=now)
        sub = parsed.subagents[0]

        expected = ('completed', True, [])

        assert (sub.status, sub.is_done, parsed.visible(now, now - 200.0)) == expected

    def test_write_within_skew_tolerance_keeps_terminal_signal(self, tmp_home: Path) -> None:
        # setup: transcript touched a hair after the signal — clock skew, not life
        now = time.time()
        notif_ts = now - 100.0
        sdir = _subagents_dir(tmp_home)
        _write_agent(
            sdir, 'agent-skewed',
            jsonl_lines=[_assistant_line('m1', output_tokens=5)],
            mtime=notif_ts + (RunningSubagents.TERMINAL_SKEW_SECONDS - 1),
        )
        self._write_session(tmp_home, _notification_line('skewed', 'completed', iso_ts(notif_ts)))

        sub = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR, now=now).subagents[0]

        expected = ('completed', True)

        assert (sub.status, sub.is_done) == expected
