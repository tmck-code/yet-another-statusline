"""Tests for the single-pass + incremental TranscriptScan.

The parity sweep is the core guarantee: tailing the transcript incrementally
(reading only newly-appended bytes) must equal a full scan at EVERY byte
boundary — proving no divergence in usage dedup, the task state machine, or
skill ordering across the offset.
"""
import json
import shutil
from pathlib import Path

import statusline_command as sl


def _skill(name: str) -> str:
    return json.dumps({'type': 'tool_use', 'name': 'Skill', 'input': {'skill': name}})


def _usage(mid: str, i: int = 0, cc: int = 0, cr: int = 0, o: int = 0) -> str:
    return json.dumps({
        'type': 'assistant',
        'message': {
            'id': mid, 'role': 'assistant',
            'usage': {
                'input_tokens': i, 'cache_creation_input_tokens': cc,
                'cache_read_input_tokens': cr, 'output_tokens': o,
            },
        },
    })


def _tcreate(subject: str, active_form: str, ts: str) -> str:
    return json.dumps({
        'timestamp': ts, 'type': 'assistant',
        'message': {'content': [{'type': 'tool_use', 'name': 'TaskCreate',
                                 'input': {'subject': subject, 'activeForm': active_form}}]},
    })


def _tupdate(task_id: int, status: str, ts: str) -> str:
    return json.dumps({
        'timestamp': ts, 'type': 'assistant',
        'message': {'content': [{'type': 'tool_use', 'name': 'TaskUpdate',
                                 'input': {'taskId': str(task_id), 'status': status}}]},
    })


def _transcript(tmp_home: Path, name: str = '123123.jsonl') -> Path:
    """A path under CLAUDE_DIR/projects so incremental tailing is enabled."""
    d = tmp_home / '.claude' / 'projects' / 'slug'
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def _clear_state(tmp_home: Path) -> None:
    shutil.rmtree(tmp_home / '.claude' / 'statusline-scan', ignore_errors=True)


def _proj(scan: sl.TranscriptScan) -> object:
    u = scan.transcript_usage()
    tl = scan.task_list()
    return (
        scan.loaded_skills().names,
        (u.input_tokens, u.cache_creation_input_tokens, u.cache_read_input_tokens, u.output_tokens),
        [(t.id, t.subject, t.active_form, t.status) for t in tl.tasks],
        tl.last_event_ts,
    )


def _scan(path: Path) -> sl.TranscriptScan:
    # _SCAN_CACHE is a module-global mutated inside transcript._scan_transcript;
    # assigning to sl._SCAN_CACHE would rebind only sl's namespace (after the
    # Phase-2 split) — the real cache lives in the transcript module.
    sl.transcript._SCAN_CACHE = None
    return sl._scan_transcript(str(path))


# A transcript covering every line kind, including a duplicate message id (must
# be counted once) and a malformed line (must be skipped). ASCII only, so a
# character cut index equals the byte offset for the sweep below.
LINES = [
    _skill('tdd'),
    _usage('m1', 10, 1, 2, 5),
    _tcreate('Do A', 'Doing A', '2026-05-27T00:00:00.000Z'),
    _usage('m1', 99, 99, 99, 99),                       # duplicate id -> ignored
    _tupdate(1, 'completed', '2026-05-27T00:01:00.000Z'),
    _usage('m2', 20, 0, 0, 7),
    _skill('python-style'),
    'totally not json but contains "usage" and "assistant"',
]
FULL = '\n'.join(LINES) + '\n'


def test_incremental_matches_full_at_every_split(tmp_home: Path) -> None:
    t = _transcript(tmp_home)
    t.write_text(FULL)
    assert sl._incremental_enabled(t), 'transcript under CLAUDE_DIR/projects should enable incremental'
    ref = _proj(sl.TranscriptScan.scan_full(str(t)))
    # sanity: the reference actually exercised dedup + task folding
    assert ref[1] == (30, 1, 2, 12), ref          # m1(10,1,2,5)+m2(20,0,0,7); dup m1 ignored
    assert ref[2] == [(1, 'Do A', 'Doing A', 'completed')], ref
    assert ref[0] == ['tdd', 'python-style'], ref

    for cut in range(len(FULL) + 1):
        _clear_state(tmp_home)
        t.write_text(FULL[:cut])    # partial prefix
        _scan(t)                    # incremental pass 1 (persists offset/state)
        t.write_text(FULL)          # complete the file (same inode)
        s2 = _scan(t)               # incremental pass 2 (tail only)
        assert _proj(s2) == ref, f'incremental != full at split {cut}'


def test_dedup_across_offset_boundary(tmp_home: Path) -> None:
    _clear_state(tmp_home)
    t = _transcript(tmp_home)
    t.write_text(_usage('a', 10) + '\n')
    assert _scan(t).transcript_usage().input_tokens == 10
    # append a duplicate 'a' (must not double-count) and a new 'b'
    t.write_text(_usage('a', 10) + '\n' + _usage('a', 10) + '\n' + _usage('b', 5) + '\n')
    assert _scan(t).transcript_usage().input_tokens == 15


def test_partial_last_line_not_counted_until_terminated(tmp_home: Path) -> None:
    _clear_state(tmp_home)
    t = _transcript(tmp_home)
    # two complete lines + an unterminated third (no trailing newline)
    t.write_text(_usage('m1', 10) + '\n' + _usage('m2', 20) + '\n' + _usage('m3', 30))
    assert _scan(t).transcript_usage().input_tokens == 30   # m3 fragment not counted
    # complete the third line
    t.write_text(_usage('m1', 10) + '\n' + _usage('m2', 20) + '\n' + _usage('m3', 30) + '\n')
    assert _scan(t).transcript_usage().input_tokens == 60   # m3 now counted exactly once


def test_truncation_resets_to_full_scan(tmp_home: Path) -> None:
    _clear_state(tmp_home)
    t = _transcript(tmp_home)
    t.write_text(_usage('a', 10) + '\n' + _usage('b', 20) + '\n')
    _scan(t)
    t.write_text(_usage('c', 5) + '\n')   # shorter -> offset past EOF -> reset
    assert _scan(t).transcript_usage().input_tokens == 5


def test_inode_change_resets_to_full_scan(tmp_home: Path) -> None:
    _clear_state(tmp_home)
    t = _transcript(tmp_home)
    t.write_text(_usage('a', 10) + '\n')
    _scan(t)
    t.unlink()
    t.write_text(_usage('b', 7) + '\n' + _usage('c', 8) + '\n')  # new inode
    assert _scan(t).transcript_usage().input_tokens == 15


def test_corrupt_state_falls_back_to_full_scan(tmp_home: Path) -> None:
    _clear_state(tmp_home)
    t = _transcript(tmp_home)
    t.write_text(_usage('a', 10) + '\n' + _usage('b', 20) + '\n')
    sp = sl._scan_state_path(t)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text('{ this is not valid json')
    assert _scan(t).transcript_usage().input_tokens == 30


def test_kill_switch_disables_incremental(tmp_home: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv('YAS_NO_INCREMENTAL', '1')
    t = _transcript(tmp_home)
    _clear_state(tmp_home)
    t.write_text(_usage('a', 10) + '\n')
    assert not sl._incremental_enabled(t)
    assert _scan(t).transcript_usage().input_tokens == 10
    assert not (tmp_home / '.claude' / 'statusline-scan').exists()  # no state written


def test_transcript_outside_projects_writes_no_state(tmp_path: Path) -> None:
    t = tmp_path / 'loose.jsonl'   # not under CLAUDE_DIR/projects
    t.write_text(_usage('a', 10) + '\n')
    assert not sl._incremental_enabled(t)
    sl.transcript._SCAN_CACHE = None
    assert sl._scan_transcript(str(t)).transcript_usage().input_tokens == 10
