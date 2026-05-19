"""Tests for SessionInfo.elapsed property."""
import os
import time

import statusline_command as sl


def test_empty_transcript_path_returns_empty_string():
    """10.2 Empty transcript path returns ''."""
    session = sl.SessionInfo(transcript_path='')
    assert session.elapsed == ''


def test_missing_transcript_file_returns_empty_string(tmp_path):
    """10.2 Non-existent transcript path returns ''."""
    session = sl.SessionInfo(transcript_path=str(tmp_path / 'nonexistent.jsonl'))
    assert session.elapsed == ''


def test_five_minutes_old_transcript(tmp_path):
    """10.3 Transcript mtime 5 min ago returns '5m'."""
    transcript = tmp_path / 'transcript.jsonl'
    transcript.write_text('{}')
    now = time.time()
    five_min_ago = now - 300
    os.utime(transcript, (five_min_ago, five_min_ago))

    session = sl.SessionInfo(transcript_path=str(transcript))
    assert session.elapsed == '5m'


def test_two_hours_two_minutes_old_transcript(tmp_path):
    """10.4 Transcript mtime 2h 2m ago returns '2h2m'."""
    transcript = tmp_path / 'transcript.jsonl'
    transcript.write_text('{}')
    now = time.time()
    # 2h 2m = 7320 seconds
    old_mtime = now - 7320
    os.utime(transcript, (old_mtime, old_mtime))

    session = sl.SessionInfo(transcript_path=str(transcript))
    assert session.elapsed == '2h2m'
