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


def _text(s: str) -> dict:
    return {'type': 'text', 'text': s}


def _tool(name: str = 'Bash') -> dict:
    return {'type': 'tool_use', 'name': name, 'input': {'command': 'ls'}}


def test_terminal_text_null_stop_reason_detects_done(tmp_home: Path) -> None:
    # Regression: some sidechain (sub-agent) transcripts NEVER emit
    # stop_reason: "end_turn". Every assistant line is either "tool_use" or null,
    # including the final result message. The agent is finished, but the strict
    # end_turn rule left end_ts == 0 so it rendered as running forever. The
    # terminal-text fallback marks it Done from the LAST assistant line: a text
    # block with no tool_use. Interstitial null-stop text lines mid-stream
    # (below) must NOT trigger it — only the final line decides.
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
    assert sub.end_ts > 0
    # 2026-05-22T18:00:10Z → epoch ≈ 1779472810
    assert 1779472809 < sub.end_ts < 1779472811


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
    # When end_turn IS present its timestamp wins; the fallback must not override
    # it with a later/earlier terminal-text timestamp.
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
    # 2026-05-22T18:00:00Z → epoch ≈ 1779472800
    assert 1779472799 < sub.end_ts < 1779472801


def test_structured_output_tool_use_detects_done(tmp_home: Path) -> None:
    # Workflow agents finish by calling StructuredOutput with stop_reason:
    # "tool_use" (not "end_turn"). This is a completion signal, not an
    # intermediate tool call awaiting results. end_ts should be set.
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
    # StructuredOutput completion should set end_ts
    assert sub.end_ts > 0
    # 2026-05-22T18:00:00Z → epoch ≈ 1779472800
    assert 1779472799 < sub.end_ts < 1779472801


def test_structured_output_null_stop_reason_detects_done(tmp_home: Path) -> None:
    # Regression: real workflow transcripts sometimes end with the
    # StructuredOutput tool_use carrying stop_reason: null (a streamed write
    # whose stop was never finalized on disk), not "tool_use". This previously
    # fell through both fallbacks, undercounting a run's done agents (e.g.
    # "12 done" when 15 were finished). A null stop on a final StructuredOutput
    # call must still be detected as done.
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
    assert sub.end_ts > 0
    assert 1779472799 < sub.end_ts < 1779472801


def test_structured_output_duplicate_message_detects_done(tmp_home: Path) -> None:
    # Bug fix: when the final message in the transcript is a duplicate
    # (same mid already seen), the StructuredOutput detection must still work.
    # This happens when a message is re-streamed (partial then final write).
    # The code must use the content from the final write, not an earlier message.
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
    # StructuredOutput completion should set end_ts even when it's a duplicate message
    assert sub.end_ts > 0
    assert 1779472799 < sub.end_ts < 1779472801
