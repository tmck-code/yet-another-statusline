"""Incremental parse_transcript: resumed fold must equal a full parse."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from helper import iso_ts
from yas.info.parsecache import TranscriptCache
from yas.info.subagents import parse_transcript

BASE = 1_700_000_000.0


def _line(
    offset: float,
    mid: str,
    *,
    out: int = 10,
    stop: str | None = None,
    content: list[dict] | None = None,
    model: str = 'claude-x',
) -> str:
    rec = {
        'type':      'assistant',
        'timestamp': iso_ts(BASE + offset),
        'message': {
            'id':          mid,
            'model':       model,
            'stop_reason': stop,
            'usage': {
                'input_tokens':                5,
                'cache_creation_input_tokens': 2,
                'cache_read_input_tokens':     100 + out,
                'output_tokens':               out,
            },
            'content': content if content is not None else [{'type': 'thinking'}],
        },
    }
    return json.dumps(rec) + '\n'


def _chunks() -> list[str]:
    return [
        _line(1, 'm1', out=5) + _line(2, 'm1', out=20, content=[{'type': 'text', 'text': 'hi'}]),
        _line(3, 'm2', out=7, model='other') + _line(4, 'm2', out=30, content=[
            {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ls'}},
        ]),
        _line(5, 'm3', out=40, stop='end_turn', content=[{'type': 'text', 'text': 'done'}]),
    ]


class TestIncrementalEquivalence:
    @pytest.mark.parametrize('resume_after', [0.0, BASE + 2.5])
    @pytest.mark.parametrize('totals_only', [False, True])
    def test_chunked_equals_full(
        self, tmp_home: Path, tmp_path: Path, resume_after: float, totals_only: bool,
    ) -> None:
        chunks = _chunks()
        path   = tmp_path / 'agent-a.jsonl'
        cache  = TranscriptCache('s1')
        # Chunk 2 is cut mid-line; the remainder arrives with chunk 3.
        cut    = len(chunks[1]) // 2
        pieces = [chunks[0], chunks[1][:cut], chunks[1][cut:] + chunks[2]]

        result = None
        with path.open('w') as fh:
            for piece in pieces:
                fh.write(piece)
                fh.flush()
                result = parse_transcript(
                    path, resume_after, cache=cache, totals_only=totals_only,
                )
                cache.save()
                cache = TranscriptCache.load('s1')
        expected = parse_transcript(path, resume_after, totals_only=totals_only)

        assert result == expected
        # message id m2 spans chunks 1/2, end_turn only in the last chunk
        assert result[0] == 5 + 2
        assert result[2] == 40
        assert result[6] == BASE + 5
        assert result[3] == BASE + 1

    def test_resume_after_run_start_and_activity(self, tmp_home: Path, tmp_path: Path) -> None:
        chunks = _chunks()
        path   = tmp_path / 'agent-b.jsonl'
        cache  = TranscriptCache('s2')
        path.write_text(chunks[0] + chunks[1])
        parse_transcript(path, BASE + 2.5, cache=cache)
        with path.open('a') as fh:
            fh.write(chunks[2])

        result   = parse_transcript(path, BASE + 2.5, cache=cache)
        expected = parse_transcript(path, BASE + 2.5)

        assert result == expected
        assert result[7] == BASE + 3
        assert result[4] == 'claude-x'
        assert result[5] == ('text', 'done', {})

    def test_message_scoped_activity_across_chunks(self, tmp_home: Path, tmp_path: Path) -> None:
        path  = tmp_path / 'agent-c.jsonl'
        cache = TranscriptCache('s3')
        path.write_text(_line(1, 'm1'))
        parse_transcript(path, cache=cache)
        with path.open('a') as fh:
            fh.write(_line(2, 'm1', content=[{'type': 'tool_use', 'name': 'Read', 'input': {'p': 'x'}}]))

        result = parse_transcript(path, cache=cache)

        assert result[5] == ('tool_use', 'Read', {'p': 'x'})
        assert result == parse_transcript(path)

    def test_non_terminal_line_clears_end_ts(self, tmp_home: Path, tmp_path: Path) -> None:
        path  = tmp_path / 'agent-d.jsonl'
        cache = TranscriptCache('s4')
        path.write_text(_line(1, 'm1', stop='end_turn'))
        assert parse_transcript(path, cache=cache)[6] == BASE + 1
        with path.open('a') as fh:
            fh.write(_line(2, 'm2'))

        result = parse_transcript(path, cache=cache)

        assert result[6] == 0.0
        assert result == parse_transcript(path)


class TestFallbackToFull:
    def test_truncation_falls_back(self, tmp_home: Path, tmp_path: Path) -> None:
        path  = tmp_path / 'agent-e.jsonl'
        cache = TranscriptCache('s5')
        path.write_text(''.join(_chunks()))
        parse_transcript(path, cache=cache)
        path.write_text(_line(1, 'z1', out=3))

        result = parse_transcript(path, cache=cache)

        assert result == parse_transcript(path)
        assert result[2] == 3

    def test_replacement_same_size_falls_back(self, tmp_home: Path, tmp_path: Path) -> None:
        path  = tmp_path / 'agent-f.jsonl'
        cache = TranscriptCache('s6')
        path.write_text(_line(1, 'aa', out=11) + _line(2, 'bb', out=12))
        parse_transcript(path, cache=cache)
        path.unlink()
        path.write_text(_line(1, 'xx', out=21) + _line(2, 'yy', out=22) + _line(3, 'zz', out=23))

        result = parse_transcript(path, cache=cache)

        assert result == parse_transcript(path)
        assert result[2] == 23

    def test_missing_file_yields_zeroes(self, tmp_home: Path, tmp_path: Path) -> None:
        result = parse_transcript(tmp_path / 'nope.jsonl', cache=TranscriptCache('s7'))

        assert result == (0, 0, 0, 0.0, '', ('', '', {}), 0.0, 0.0, 0.0)
