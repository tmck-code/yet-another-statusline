"""Tests for TranscriptUsage.from_transcript."""
import json
from pathlib import Path

import statusline_command as sl
import yas.info.transcript as transcript


def _assistant_line(msg_id: str, input_tokens: int = 0, cache_creation: int = 0, cache_read: int = 0, output_tokens: int = 0) -> str:
    return json.dumps({
        'type': 'assistant',
        'message': {
            'id': msg_id,
            'role': 'assistant',
            'usage': {
                'input_tokens': input_tokens,
                'cache_creation_input_tokens': cache_creation,
                'cache_read_input_tokens': cache_read,
                'output_tokens': output_tokens,
            },
        },
    })


def test_missing_path_returns_empty() -> None:
    """Missing path returns TranscriptUsage()."""
    result = transcript.TranscriptUsage.from_transcript('/nonexistent/path.jsonl')
    assert result == transcript.TranscriptUsage()


def test_two_distinct_assistant_messages_sum_correctly(tmp_path: Path) -> None:
    """Two distinct assistant messages with usage sum correctly."""
    p = tmp_path / 'transcript.jsonl'
    p.write_text(
        _assistant_line('a', input_tokens=10, output_tokens=20) + '\n' +
        _assistant_line('b', input_tokens=10, output_tokens=20) + '\n'
    )
    result = transcript.TranscriptUsage.from_transcript(str(p))
    assert result.input_tokens == 20
    assert result.output_tokens == 40


def test_duplicate_message_id_counted_once(tmp_path: Path) -> None:
    """Duplicate message ids are counted only once."""
    p = tmp_path / 'transcript.jsonl'
    line = _assistant_line('a', input_tokens=10, output_tokens=20)
    p.write_text(line + '\n' + line + '\n')

    result = transcript.TranscriptUsage.from_transcript(str(p))
    assert result.input_tokens == 10
    assert result.output_tokens == 20


def test_malformed_line_skipped(tmp_path: Path) -> None:
    """Malformed line interleaved with valid lines does not raise, valid line counted."""
    p = tmp_path / 'transcript.jsonl'
    p.write_text(
        'not valid json with "usage" and "assistant" keyword\n' +
        _assistant_line('a', input_tokens=5, output_tokens=10) + '\n'
    )
    result = transcript.TranscriptUsage.from_transcript(str(p))
    assert result.input_tokens == 5
    assert result.output_tokens == 10
