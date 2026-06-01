"""Tests for RunningSubagents.from_session."""
import json
import os
import time
from pathlib import Path


import yas.info.subagents as subagents
from yas.info.subagents import RunningSubagent, RunningSubagents


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


def test_stale_entry_excluded(tmp_home: Path) -> None:
    now = time.time()
    stale_mtime = now - RunningSubagents.STALE_SECONDS - 1
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-stale', mtime=stale_mtime)

    result = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    assert result.subagents == []


def test_stale_window_is_20_seconds() -> None:
    assert RunningSubagents.STALE_SECONDS == 20


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
    assert sub.last_activity == ('text', '', {})


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
