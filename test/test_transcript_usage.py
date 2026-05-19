"""Tests for TranscriptUsage.from_transcript."""
import json

import statusline_command as sl


def _assistant_line(msg_id, input_tokens=0, cache_creation=0, cache_read=0, output_tokens=0):
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


def test_missing_path_returns_empty():
    """4.2 Missing path returns TranscriptUsage()."""
    result = sl.TranscriptUsage.from_transcript('/nonexistent/path.jsonl')
    assert result == sl.TranscriptUsage()


def test_two_distinct_assistant_messages_sum_correctly(tmp_path):
    """4.3 Two distinct assistant messages with usage sum correctly."""
    p = tmp_path / 'transcript.jsonl'
    p.write_text(
        _assistant_line('a', input_tokens=10, output_tokens=20) + '\n' +
        _assistant_line('b', input_tokens=10, output_tokens=20) + '\n'
    )
    result = sl.TranscriptUsage.from_transcript(str(p))
    assert result.input_tokens == 20
    assert result.output_tokens == 40


def test_duplicate_message_id_counted_once(tmp_path):
    """4.4 Duplicate message ids are counted only once."""
    p = tmp_path / 'transcript.jsonl'
    line = _assistant_line('a', input_tokens=10, output_tokens=20)
    p.write_text(line + '\n' + line + '\n')

    result = sl.TranscriptUsage.from_transcript(str(p))
    assert result.input_tokens == 10
    assert result.output_tokens == 20


def test_malformed_line_skipped(tmp_path):
    """4.5 Malformed line interleaved with valid lines does not raise, valid line counted."""
    p = tmp_path / 'transcript.jsonl'
    p.write_text(
        'not valid json with "usage" and "assistant" keyword\n' +
        _assistant_line('a', input_tokens=5, output_tokens=10) + '\n'
    )
    result = sl.TranscriptUsage.from_transcript(str(p))
    assert result.input_tokens == 5
    assert result.output_tokens == 10
