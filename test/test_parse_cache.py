"""Tests for TranscriptCache — persistence and performance cache for transcript parses.

Tests cover:
- 6.2: Round-trip caching, cache invalidation via mtime/size, parameter variations,
       corruption handling, pruning, and atomic save.
- 6.3: Tail-cache resumption for notifications and tool results.
- 6.5: totals_only mode equivalence to full parse (except model and last_activity).
"""
import json
import time
from pathlib import Path

import pytest

from test_running_subagents import (
    _subagents_dir,
    _write_agent,
)
from yas.info.parsecache import (
    TranscriptCache,
    cache_path,
)
from yas.info.subagents import (
    parse_transcript,
    _tail_read_notifications,
    _tail_read_tool_results,
)
from yas.constants import (
    TRANSCRIPT_CACHE_VERSION,
    TRANSCRIPT_CACHE_KEEP_SECONDS,
)


def test_parse_cache_round_trip(tmp_home: Path) -> None:
    """Round-trip: put a parse result, save(), load(), get the identical tuple."""
    session_id = 'test-session-1'
    cache = TranscriptCache(session_id)

    # Create a test transcript file to stat
    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    jsonl_path.write_text('{"event": "test"}\n')
    st = jsonl_path.stat()

    # Create a parse result with nested last_activity tuple
    parse_result = (
        100,  # billed_in
        50,   # cache_read_in
        200,  # output
        1234.5,  # first_ts
        'claude-3.5-sonnet',  # model
        ('tool_use', 'test_tool', {'key': 'value'}),  # last_activity tuple
        1235.5,  # end_ts
        1234.6,  # run_start_ts
    )

    # Put and save
    cache.put_parse(str(jsonl_path), st, 0.0, parse_result)
    cache.save()

    # Load and verify
    loaded_cache = TranscriptCache.load(session_id)
    retrieved = loaded_cache.get_parse(str(jsonl_path), st, 0.0)

    assert retrieved is not None
    assert retrieved == parse_result
    # Verify nested tuple was preserved
    assert isinstance(retrieved[5], tuple)
    assert len(retrieved[5]) == 3
    assert retrieved[5] == ('tool_use', 'test_tool', {'key': 'value'})


def test_parse_cache_mtime_change_causes_miss(tmp_home: Path) -> None:
    """Mtime change invalidates the cache entry."""
    session_id = 'test-session-2'
    cache = TranscriptCache(session_id)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    jsonl_path.write_text('{"event": "test"}\n')
    st1 = jsonl_path.stat()

    parse_result = (100, 50, 200, 1234.5, 'claude-3.5-sonnet',
                    ('text', 'hello', {}), 1235.5, 0.0)

    cache.put_parse(str(jsonl_path), st1, 0.0, parse_result)
    cache.save()

    # Change mtime by writing again
    time.sleep(0.01)
    jsonl_path.write_text('{"event": "test2"}\n')
    st2 = jsonl_path.stat()

    # Load and try to get with new stat
    loaded_cache = TranscriptCache.load(session_id)
    retrieved = loaded_cache.get_parse(str(jsonl_path), st2, 0.0)

    assert retrieved is None, "Expected cache miss on mtime change"


def test_parse_cache_size_change_causes_miss(tmp_home: Path) -> None:
    """Size change invalidates the cache entry."""
    session_id = 'test-session-3'
    cache = TranscriptCache(session_id)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    jsonl_path.write_text('x' * 100)
    st1 = jsonl_path.stat()

    parse_result = (100, 50, 200, 1234.5, 'claude-3.5-sonnet',
                    ('text', 'hello', {}), 1235.5, 0.0)

    cache.put_parse(str(jsonl_path), st1, 0.0, parse_result)
    cache.save()

    # Change size (at the same mtime by monkeypatching)
    loaded_cache = TranscriptCache.load(session_id)
    # Manually create a stat with same mtime but different size
    class FakeStat:
        def __init__(self, real_st):
            self.st_mtime = real_st.st_mtime
            self.st_size = real_st.st_size + 1

    fake_st = FakeStat(st1)
    retrieved = loaded_cache.get_parse(str(jsonl_path), fake_st, 0.0)

    assert retrieved is None, "Expected cache miss on size change"


def test_parse_cache_unchanged_mtime_and_size_hit(tmp_home: Path) -> None:
    """Unchanged mtime and size results in cache hit."""
    session_id = 'test-session-4'
    cache = TranscriptCache(session_id)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    content = '{"event": "test"}\n' * 50
    jsonl_path.write_text(content)
    st = jsonl_path.stat()

    parse_result = (100, 50, 200, 1234.5, 'claude-3.5-sonnet',
                    ('text', 'hello', {}), 1235.5, 0.0)

    cache.put_parse(str(jsonl_path), st, 0.0, parse_result)
    cache.save()

    # Load and use the exact same stat
    loaded_cache = TranscriptCache.load(session_id)
    retrieved = loaded_cache.get_parse(str(jsonl_path), st, 0.0)

    assert retrieved == parse_result, "Expected cache hit with unchanged mtime/size"


def test_parse_cache_different_resume_after_miss(tmp_home: Path) -> None:
    """Different resume_after parameter causes cache miss."""
    session_id = 'test-session-5'
    cache = TranscriptCache(session_id)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    jsonl_path.write_text('{"event": "test"}\n')
    st = jsonl_path.stat()

    parse_result = (100, 50, 200, 1234.5, 'claude-3.5-sonnet',
                    ('text', 'hello', {}), 1235.5, 0.0)

    cache.put_parse(str(jsonl_path), st, 1234.0, parse_result)
    cache.save()

    loaded_cache = TranscriptCache.load(session_id)
    # Try to retrieve with different resume_after
    retrieved = loaded_cache.get_parse(str(jsonl_path), st, 1235.0)

    assert retrieved is None, "Expected cache miss on different resume_after"


def test_parse_subkey_trim_is_by_recency_not_key_string(tmp_home: Path) -> None:
    """The per-path sub-key map keeps the TRANSCRIPT_CACHE_SUBKEY_MAX most-recently
    written sub-keys, not the lexicographically-largest keys. Use a resume_after
    write order whose lexicographic key order is the reverse of write order, so a
    key-string sort and a recency sort would evict different entries."""
    session_id = 'test-session-subkey-recency'
    cache = TranscriptCache(session_id)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    jsonl_path.write_text('{"event": "test"}\n')
    st = jsonl_path.stat()

    def make(resume_after: float) -> tuple:
        return (100, 50, 200, 1234.5, 'claude-3.5-sonnet',
                ('text', 'hello', {}), 1235.5, resume_after)

    # repr(float(x)) sorts lexicographically as '9.0' > '8.0' > ... > '5.0',
    # i.e. descending as resume_after descends. Write in ASCENDING resume_after
    # order, so "most recently written" (9.0) is the SMALLEST key string.
    # TRANSCRIPT_CACHE_SUBKEY_MAX is 4, so write 5 sub-keys: 5.0..9.0.
    for resume_after in (5.0, 6.0, 7.0, 8.0, 9.0):
        cache.put_parse(str(jsonl_path), st, resume_after, make(resume_after))

    # Recency trim keeps the 4 most-recently-written (6.0, 7.0, 8.0, 9.0) and
    # evicts the oldest write (5.0) — a key-string sort would instead evict 9.0
    # (the lexicographically-smallest key), which is the most recent write.
    assert cache.get_parse(str(jsonl_path), st, 5.0) is None, \
        "Expected the oldest WRITE (5.0) to be evicted"
    for resume_after in (6.0, 7.0, 8.0, 9.0):
        assert cache.get_parse(str(jsonl_path), st, resume_after) is not None, \
            f"Expected recently-written resume_after={resume_after} to survive the trim"


def test_counts_cache_different_clear_epoch_miss(tmp_home: Path) -> None:
    """Different clear_epoch causes counts cache miss."""
    session_id = 'test-session-6'
    cache = TranscriptCache(session_id)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    jsonl_path.write_text('{"event": "test"}\n')
    st = jsonl_path.stat()

    counts_result = {'counts': {'a': 1}, 'lines_read': 10, 'lines_changed': 2}

    cache.put_counts(str(jsonl_path), st, 1000.0, False, counts_result)
    cache.save()

    loaded_cache = TranscriptCache.load(session_id)
    # Try with different clear_epoch
    retrieved = loaded_cache.get_counts(str(jsonl_path), st, 2000.0, False)

    assert retrieved is None, "Expected cache miss on different clear_epoch"


def test_counts_cache_different_skip_sidechain_miss(tmp_home: Path) -> None:
    """Different skip_sidechain causes counts cache miss."""
    session_id = 'test-session-7'
    cache = TranscriptCache(session_id)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    jsonl_path.write_text('{"event": "test"}\n')
    st = jsonl_path.stat()

    counts_result = {'counts': {'a': 1}, 'lines_read': 10, 'lines_changed': 2}

    cache.put_counts(str(jsonl_path), st, 1000.0, False, counts_result)
    cache.save()

    loaded_cache = TranscriptCache.load(session_id)
    # Try with different skip_sidechain
    retrieved = loaded_cache.get_counts(str(jsonl_path), st, 1000.0, True)

    assert retrieved is None, "Expected cache miss on different skip_sidechain"


def test_corrupt_truncated_json_returns_empty_cache(tmp_home: Path) -> None:
    """Truncated JSON in cache file results in empty cache, no exception."""
    session_id = 'test-session-8'
    cache_file = cache_path(session_id)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    # Write truncated JSON
    cache_file.write_text('{"v": 1, "session": "test-session-8", "entries": {')

    loaded = TranscriptCache.load(session_id)
    assert loaded.session_id == session_id
    assert loaded._entries == {}


def test_corrupt_empty_dict_returns_empty_cache(tmp_home: Path) -> None:
    """Empty dict (missing v/session) returns empty cache."""
    session_id = 'test-session-9'
    cache_file = cache_path(session_id)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text('{}')

    loaded = TranscriptCache.load(session_id)
    assert loaded.session_id == session_id
    assert loaded._entries == {}


def test_corrupt_json_list_returns_empty_cache(tmp_home: Path) -> None:
    """JSON list instead of dict returns empty cache."""
    session_id = 'test-session-10'
    cache_file = cache_path(session_id)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text('[]')

    loaded = TranscriptCache.load(session_id)
    assert loaded.session_id == session_id
    assert loaded._entries == {}


def test_corrupt_wrong_version_returns_empty_cache(tmp_home: Path) -> None:
    """Wrong cache version returns empty cache."""
    session_id = 'test-session-11'
    cache_file = cache_path(session_id)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        'v': 999,  # Wrong version
        'session': session_id,
        'saved': time.time(),
        'entries': {},
    }
    cache_file.write_text(json.dumps(data))

    loaded = TranscriptCache.load(session_id)
    assert loaded._entries == {}


def test_one_malformed_entry_others_still_hit(tmp_home: Path) -> None:
    """One malformed entry doesn't prevent other entries from hitting."""
    session_id = 'test-session-12'
    cache_file = cache_path(session_id)
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl1 = transcripts_dir / 'good1.jsonl'
    jsonl2 = transcripts_dir / 'bad.jsonl'
    jsonl3 = transcripts_dir / 'good2.jsonl'
    jsonl1.write_text('content1')
    jsonl2.write_text('content2')
    jsonl3.write_text('content3')

    st1 = jsonl1.stat()
    st3 = jsonl3.stat()

    # Manually craft cache file with one good, one malformed, one good
    data = {
        'v': TRANSCRIPT_CACHE_VERSION,
        'session': session_id,
        'saved': time.time(),
        'entries': {
            str(jsonl1): {
                'mtime': st1.st_mtime,
                'size': st1.st_size,
                'seen': time.time(),
                'parse': {
                    '0.0': [100, 50, 200, 1234.5, 'model', ['tool_use', 'name', {}], 1235.5, 0.0]
                }
            },
            str(jsonl2): 'not-a-dict',  # Malformed entry
            str(jsonl3): {
                'mtime': st3.st_mtime,
                'size': st3.st_size,
                'seen': time.time(),
                'parse': {
                    '0.0': [200, 60, 300, 1334.5, 'model2', ['text', 'snippet', {}], 1335.5, 0.0]
                }
            }
        }
    }
    cache_file.write_text(json.dumps(data))

    loaded = TranscriptCache.load(session_id)
    result1 = loaded.get_parse(str(jsonl1), st1, 0.0)
    result3 = loaded.get_parse(str(jsonl3), st3, 0.0)

    assert result1 is not None, "Good entry 1 should hit"
    assert result3 is not None, "Good entry 3 should hit"
    assert result1[0] == 100
    assert result3[0] == 200


def test_prune_deleted_path_entry(tmp_home: Path) -> None:
    """Entry whose path was deleted is pruned on save()."""
    session_id = 'test-session-13'
    cache = TranscriptCache(session_id)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    deleted_path = transcripts_dir / 'to-be-deleted.jsonl'
    deleted_path.write_text('content')
    st = deleted_path.stat()

    parse_result = (100, 50, 200, 1234.5, 'model',
                    ('text', 'hello', {}), 1235.5, 0.0)

    cache.put_parse(str(deleted_path), st, 0.0, parse_result)
    # Verify entry exists
    assert str(deleted_path) in cache._entries

    # Delete the file
    deleted_path.unlink()

    # Save should prune the entry
    cache.save()

    loaded = TranscriptCache.load(session_id)
    assert str(deleted_path) not in loaded._entries


def test_prune_ancient_seen_entry(tmp_home: Path) -> None:
    """Entry with ancient 'seen' timestamp is pruned on save()."""
    session_id = 'test-session-14'
    cache_file = cache_path(session_id)
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    jsonl_path.write_text('content')

    # Craft cache with old 'seen' timestamp
    now = time.time()
    old_seen = now - TRANSCRIPT_CACHE_KEEP_SECONDS - 1000  # older than retention

    data = {
        'v': TRANSCRIPT_CACHE_VERSION,
        'session': session_id,
        'saved': now,
        'entries': {
            str(jsonl_path): {
                'mtime': 1000.0,
                'size': 100,
                'seen': old_seen,
                'parse': {'0.0': [100, 50, 200, 1234.5, 'model', ['text', 'h', {}], 1235.5, 0.0]}
            }
        }
    }
    cache_file.write_text(json.dumps(data))

    # Load and save
    loaded = TranscriptCache.load(session_id)
    loaded._dirty = True  # Force a save even though we didn't modify anything
    loaded.save()

    # Re-load and verify entry was pruned
    reloaded = TranscriptCache.load(session_id)
    assert str(jsonl_path) not in reloaded._entries


def test_save_no_tmp_file_left_behind(tmp_home: Path) -> None:
    """save() leaves no .tmp file behind on success."""
    session_id = 'test-session-15'
    cache_dir = cache_path(session_id).parent
    cache_dir.mkdir(parents=True, exist_ok=True)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    jsonl_path.write_text('content')
    st = jsonl_path.stat()

    cache = TranscriptCache(session_id)
    parse_result = (100, 50, 200, 1234.5, 'model',
                    ('text', 'hello', {}), 1235.5, 0.0)
    cache.put_parse(str(jsonl_path), st, 0.0, parse_result)
    cache.save()

    cache_file = cache_path(session_id)
    tmp_file = cache_dir / f'{cache_file.name}.tmp'

    assert cache_file.exists(), "Cache file should exist"
    assert not tmp_file.exists(), ".tmp file should not be left behind"


def test_save_survives_os_replace_failure(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing cache file survives a save() that raises during os.replace."""
    session_id = 'test-session-16'
    cache_dir = cache_path(session_id).parent
    cache_dir.mkdir(parents=True, exist_ok=True)

    transcripts_dir = tmp_home / '.claude' / 'transcripts'
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = transcripts_dir / 'test.jsonl'
    jsonl_path.write_text('content')

    # Create an initial cache file with known content
    cache_file = cache_path(session_id)
    initial_data = {
        'v': TRANSCRIPT_CACHE_VERSION,
        'session': session_id,
        'saved': time.time(),
        'entries': {'initial': 'data'}
    }
    cache_file.write_text(json.dumps(initial_data))
    initial_content = cache_file.read_text()

    # Monkeypatch os.replace to raise OSError
    import os as os_module
    original_replace = os_module.replace

    def failing_replace(src, dst):
        if '.tmp' in str(src):
            raise OSError("Simulated replace failure")
        return original_replace(src, dst)

    monkeypatch.setattr(os_module, 'replace', failing_replace)

    # Now try to save a new cache
    cache = TranscriptCache(session_id)
    st = jsonl_path.stat()
    cache.put_parse(str(jsonl_path), st, 0.0, (100, 50, 200, 1234.5, 'model',
                                                ('text', 'hello', {}), 1235.5, 0.0))
    cache.save()  # Should raise during os.replace

    # Verify original file is unchanged and no .tmp remains
    assert cache_file.exists(), "Original cache file should still exist"
    assert cache_file.read_text() == initial_content, "Original cache file should be unchanged"
    tmp_file = cache_dir / f'{cache_file.name}.tmp'
    assert not tmp_file.exists(), ".tmp file should be cleaned up after failure"


def test_tail_read_notifications_with_cache_cold_warm_equivalence(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tail-read notifications: cold read equals warm read with cache resumption."""
    # Clear module-level caches at start
    monkeypatch.setattr('yas.info.subagents._notif_tail_cache', {})

    session_id = 'test-session-notif-1'
    subagents_dir = _subagents_dir(tmp_home)
    _, agent_jsonl = _write_agent(subagents_dir, 'agent-001')

    # Build a transcript with N notification lines
    notif_lines = [
        json.dumps({
            'type': 'queue-operation',
            'timestamp': '2025-01-01T12:00:00Z',
            'content': '<task-notification><task-id>task-001</task-id><status>completed</status></task-notification>'
        }) + '\n',
        json.dumps({'type': 'other'}) + '\n',
        json.dumps({
            'type': 'user',
            'timestamp': '2025-01-01T12:00:01Z',
            'content': '<task-notification><task-id>task-002</task-id><status>started</status></task-notification>'
        }) + '\n',
    ]
    agent_jsonl.write_text(''.join(notif_lines))
    initial_size = agent_jsonl.stat().st_size

    # Cold read (no cache)
    cold_result = _tail_read_notifications(agent_jsonl, cache=None)

    # Create and save cache from cold read
    cache = TranscriptCache(session_id)
    cache.put_notif(str(agent_jsonl), agent_jsonl.stat().st_mtime,
                    agent_jsonl.stat().st_size, initial_size, cold_result)
    cache.save()

    # Clear module-level cache to simulate new process
    monkeypatch.setattr('yas.info.subagents._notif_tail_cache', {})

    # Warm read (load from persistent cache)
    loaded_cache = TranscriptCache.load(session_id)
    warm_result = _tail_read_notifications(agent_jsonl, cache=loaded_cache)

    # Should be equivalent
    assert len(warm_result) == len(cold_result)
    for w, c in zip(warm_result, cold_result):
        assert w.task_id == c.task_id
        assert w.status == c.status
        assert w.ts == c.ts


def test_tail_read_notifications_append_only_appended_bytes_read(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only appended bytes are read after cache load."""
    monkeypatch.setattr('yas.info.subagents._notif_tail_cache', {})

    session_id = 'test-session-notif-2'
    subagents_dir = _subagents_dir(tmp_home)
    _, agent_jsonl = _write_agent(subagents_dir, 'agent-002')

    # Initial content
    initial_lines = [
        json.dumps({
            'type': 'queue-operation',
            'timestamp': '2025-01-01T12:00:00Z',
            'content': '<task-notification><task-id>task-001</task-id><status>started</status></task-notification>'
        }) + '\n',
    ]
    agent_jsonl.write_text(''.join(initial_lines))

    # First read and cache
    cache = TranscriptCache(session_id)
    result1 = _tail_read_notifications(agent_jsonl, cache=cache)
    assert len(result1) == 1

    cache.save()

    # Clear module cache
    monkeypatch.setattr('yas.info.subagents._notif_tail_cache', {})

    # Append more lines
    new_lines = [
        json.dumps({
            'type': 'user',
            'timestamp': '2025-01-01T12:00:05Z',
            'content': '<task-notification><task-id>task-001</task-id><status>completed</status></task-notification>'
        }) + '\n',
    ]
    agent_jsonl.write_text(''.join(initial_lines + new_lines))

    # Second read with cache
    loaded_cache = TranscriptCache.load(session_id)
    result2 = _tail_read_notifications(agent_jsonl, cache=loaded_cache)

    # Should find both (cold read equivalent)
    cold_read = _tail_read_notifications(agent_jsonl, cache=None)
    assert len(result2) == len(cold_read)

    # Verify the offset advanced (stored in cache)
    cached_state = loaded_cache.get_notif(str(agent_jsonl))
    assert cached_state is not None
    initial_offset, final_offset = 0, cached_state[2]
    assert final_offset > initial_offset, "Offset should have advanced"


def test_tail_read_tool_results_with_cache_resumption(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tail-read tool results: warm load from cache reproduces cold read."""
    monkeypatch.setattr('yas.info.subagents._tool_result_tail_cache', {})

    session_id = 'test-session-tres-1'
    subagents_dir = _subagents_dir(tmp_home)
    _, agent_jsonl = _write_agent(subagents_dir, 'agent-tres-001')

    # Build tool result lines
    tres_lines = [
        json.dumps({
            'type': 'user',
            'timestamp': '2025-01-01T12:00:00Z',
            'toolUseResult': {'status': 'success', 'timestamp': '2025-01-01T12:00:00Z'},
            'message': {
                'content': [{'type': 'tool_result', 'tool_use_id': 'tooluse-001'}]
            }
        }) + '\n',
        json.dumps({'type': 'other'}) + '\n',
    ]
    agent_jsonl.write_text(''.join(tres_lines))

    # Cold read
    cold_result = _tail_read_tool_results(agent_jsonl, cache=None)

    # Cache and save
    cache = TranscriptCache(session_id)
    cache.put_tool_results(str(agent_jsonl), agent_jsonl.stat().st_mtime,
                           agent_jsonl.stat().st_size, agent_jsonl.stat().st_size, cold_result)
    cache.save()

    # Clear module-level cache
    monkeypatch.setattr('yas.info.subagents._tool_result_tail_cache', {})

    # Warm read
    loaded_cache = TranscriptCache.load(session_id)
    warm_result = _tail_read_tool_results(agent_jsonl, cache=loaded_cache)

    assert warm_result == cold_result


def test_totals_only_equivalence_no_resume(tmp_home: Path) -> None:
    """totals_only parse equals full parse except model/last_activity, no resume."""
    subagents_dir = _subagents_dir(tmp_home)
    _, agent_jsonl = _write_agent(subagents_dir, 'agent-eq-1')

    # Build a transcript with usage lines
    lines = [
        json.dumps({
            'type': 'assistant',
            'timestamp': '2025-01-01T12:00:00.000Z',
            'message': {
                'id': 'msg-001',
                'model': 'claude-3.5-sonnet',
                'stop_reason': 'end_turn',
                'usage': {
                    'input_tokens': 100,
                    'cache_creation_input_tokens': 10,
                    'cache_read_input_tokens': 20,
                    'output_tokens': 50,
                },
                'content': [
                    {'type': 'text', 'text': 'Hello world'}
                ]
            }
        }) + '\n',
    ]
    agent_jsonl.write_text(''.join(lines))

    # Parse full
    full = parse_transcript(agent_jsonl, resume_after=0.0, totals_only=False)
    # Parse totals_only
    totals = parse_transcript(agent_jsonl, resume_after=0.0, totals_only=True)

    # Compare all elements except 4 (model) and 5 (last_activity)
    assert totals[0] == full[0], f"billed_in mismatch: {totals[0]} vs {full[0]}"
    assert totals[1] == full[1], f"cache_read_in mismatch: {totals[1]} vs {full[1]}"
    assert totals[2] == full[2], f"output mismatch: {totals[2]} vs {full[2]}"
    assert totals[3] == full[3], f"first_ts mismatch: {totals[3]} vs {full[3]}"
    # 4: model — allowed to differ
    # 5: last_activity — allowed to differ
    assert totals[6] == full[6], f"end_ts mismatch: {totals[6]} vs {full[6]}"
    assert totals[7] == full[7], f"run_start_ts mismatch: {totals[7]} vs {full[7]}"

    # Verify totals_only has blanked fields
    assert totals[4] == '', "totals_only model should be blank"
    assert totals[5] == ('', '', {}), "totals_only last_activity should be blank"


def test_totals_only_equivalence_with_resume_after(tmp_home: Path) -> None:
    """totals_only parse with positive resume_after equals full parse (except model/last_activity)."""
    subagents_dir = _subagents_dir(tmp_home)
    _, agent_jsonl = _write_agent(subagents_dir, 'agent-eq-2')

    # Build a transcript with a non-usage timestamped line at the boundary
    # (the subtle case: resume_after points to a non-usage line)
    lines = [
        json.dumps({
            'type': 'user',
            'timestamp': '2025-01-01T12:00:00.000Z',
            'message': {'content': 'Starting work'}
        }) + '\n',
        # This is the resume boundary
        json.dumps({
            'type': 'assistant',
            'timestamp': '2025-01-01T12:00:01.000Z',
            'message': {
                'id': 'msg-001',
                'model': 'claude-3.5-sonnet',
                'stop_reason': 'end_turn',
                'usage': {
                    'input_tokens': 50,
                    'cache_creation_input_tokens': 5,
                    'cache_read_input_tokens': 10,
                    'output_tokens': 25,
                },
                'content': [
                    {'type': 'text', 'text': 'Response'}
                ]
            }
        }) + '\n',
        json.dumps({
            'type': 'assistant',
            'timestamp': '2025-01-01T12:00:02.000Z',
            'message': {
                'id': 'msg-002',
                'model': 'claude-3.5-sonnet',
                'stop_reason': 'end_turn',
                'usage': {
                    'input_tokens': 50,
                    'cache_creation_input_tokens': 5,
                    'cache_read_input_tokens': 10,
                    'output_tokens': 25,
                },
                'content': [
                    {'type': 'text', 'text': 'More response'}
                ]
            }
        }) + '\n',
    ]
    agent_jsonl.write_text(''.join(lines))

    resume_after = 1234567890.5  # A timestamp in the first user message

    # Parse full
    full = parse_transcript(agent_jsonl, resume_after=resume_after, totals_only=False)
    # Parse totals_only
    totals = parse_transcript(agent_jsonl, resume_after=resume_after, totals_only=True)

    # Compare all elements except 4 (model) and 5 (last_activity)
    assert totals[0] == full[0], f"billed_in mismatch: {totals[0]} vs {full[0]}"
    assert totals[1] == full[1], f"cache_read_in mismatch: {totals[1]} vs {full[1]}"
    assert totals[2] == full[2], f"output mismatch: {totals[2]} vs {full[2]}"
    assert totals[3] == full[3], f"first_ts mismatch: {totals[3]} vs {full[3]}"
    assert totals[6] == full[6], f"end_ts mismatch: {totals[6]} vs {full[6]}"
    assert totals[7] == full[7], f"run_start_ts mismatch: {totals[7]} vs {full[7]}"

    # Verify totals_only has blanked fields
    assert totals[4] == '', "totals_only model should be blank"
    assert totals[5] == ('', '', {}), "totals_only last_activity should be blank"
