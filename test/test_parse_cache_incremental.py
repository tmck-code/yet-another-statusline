"""Tests for the incremental fold API in TranscriptCache (get_fold/put_fold/fold_file)."""
import json
import os
from pathlib import Path

from yas.constants import TRANSCRIPT_CACHE_VERSION
from yas.info.parsecache import (
    TranscriptCache,
    cache_path,
    fold_file,
    read_complete_lines,
)


def _init() -> dict[str, list[str]]:
    return {'lines': []}


def _fold(state: dict[str, list[str]], lines: list[bytes]) -> dict[str, list[str]]:
    state['lines'].extend(line.decode() for line in lines)
    return state


def _run(cache: TranscriptCache | None, path: Path) -> dict[str, list[str]]:
    return fold_file(cache, str(path), path.stat(), 'k', 'sub', _init, _fold)


def _append(path: Path, text: str) -> None:
    with open(path, 'ab') as f:
        f.write(text.encode())


def test_resume_equals_full_parse_across_chunks(tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('')
    cache = TranscriptCache('s')
    for chunk in ('alpha\nbe', 'ta\ngamma\n', 'delta\n', 'eps', 'ilon\n'):
        _append(path, chunk)
        result = _run(cache, path)
        assert result == _run(None, path)
    assert result['lines'] == ['alpha', 'beta', 'gamma', 'delta', 'epsilon']


def test_half_line_not_consumed_until_complete(tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('one\ntw')
    cache = TranscriptCache('s')

    assert _run(cache, path)['lines'] == ['one']
    assert cache.get_fold(str(path), path.stat(), 'k', 'sub')[1] == 4

    _append(path, 'o\n')
    assert _run(cache, path)['lines'] == ['one', 'two']


def test_read_complete_lines_no_newline(tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('abc')
    assert read_complete_lines(str(path), 0) == (b'', 0, '')


def test_resume_only_folds_new_lines(tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('a\nb\n')
    cache = TranscriptCache('s')
    _run(cache, path)
    _append(path, 'c\n')
    seen: list[list[bytes]] = []

    def spy(state: dict[str, list[str]], lines: list[bytes]) -> dict[str, list[str]]:
        seen.append(lines)
        return _fold(state, lines)

    result = fold_file(cache, str(path), path.stat(), 'k', 'sub', _init, spy)
    assert seen == [[b'c']]
    assert result['lines'] == ['a', 'b', 'c']


def test_truncation_triggers_full_reparse(tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('aaaa\nbbbb\ncccc\n')
    cache = TranscriptCache('s')
    _run(cache, path)
    path.write_text('aaaa\n')
    assert cache.get_fold(str(path), path.stat(), 'k', 'sub') is None
    assert _run(cache, path)['lines'] == ['aaaa']


def test_replacement_new_inode_triggers_full_reparse(tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('aaaa\nbbbb\n')
    cache = TranscriptCache('s')
    _run(cache, path)
    other = tmp_path / 'other'
    other.write_text('aaaa\nbbbb\ncccc\n')
    os.replace(other, path)
    assert cache.get_fold(str(path), path.stat(), 'k', 'sub') is None
    assert _run(cache, path)['lines'] == ['aaaa', 'bbbb', 'cccc']


def test_same_size_prefix_rewrite_triggers_full_reparse(tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('aaaa\nbbbb\n')
    cache = TranscriptCache('s')
    _run(cache, path)
    with open(path, 'r+b') as f:
        f.write(b'zzzz\nbbbb\ncc\n')
    assert cache.get_fold(str(path), path.stat(), 'k', 'sub') is None
    assert _run(cache, path)['lines'] == ['zzzz', 'bbbb', 'cc']


def test_state_survives_save_and_load(tmp_home: Path, tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('a\nb\n')
    cache = TranscriptCache('sess')
    _run(cache, path)
    cache.save()

    loaded = TranscriptCache.load('sess')
    _append(path, 'c\n')
    assert _run(loaded, path)['lines'] == ['a', 'b', 'c']


def test_subkeys_trimmed(tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('a\n')
    cache = TranscriptCache('s')
    st = path.stat()
    for i in range(7):
        cache.put_fold(str(path), st, 'k', f's{i}', {}, 2, '')
    assert len(cache._entries[str(path)]['fold']['k']) == 4


def test_v2_cache_file_discarded(tmp_home: Path, tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('a\n')
    cp = cache_path('sess')
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({'v': 2, 'session': 'sess', 'saved': 0, 'entries': {str(path): {'seen': 1e12}}}))
    assert TRANSCRIPT_CACHE_VERSION == 4
    assert TranscriptCache.load('sess')._entries == {}


def test_cache_none_full_parse(tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('a\nb\nc')
    assert _run(None, path)['lines'] == ['a', 'b']


def test_unreadable_path_returns_init(tmp_path: Path) -> None:
    path = tmp_path / 't.jsonl'
    path.write_text('a\n')
    st = path.stat()
    path.unlink()
    assert fold_file(TranscriptCache('s'), str(path), st, 'k', '', _init, _fold) == {'lines': []}
