"""Tests for SessionView.elapsed (mtime-based elapsed formatting)."""
import json
import os
import time
from pathlib import Path

import pytest

from yas.config import Config
from yas.info import SessionView
from yas.session import SessionInfo

SESSION_FILE = Path(__file__).parent.parent / 'ops' / 'session-info-example.json'


def _view_with_transcript(transcript_path: str, now: float | None = None) -> SessionView:
    session_data = json.loads(SESSION_FILE.read_text())
    session_data['transcript_path'] = transcript_path
    session = SessionInfo.from_dict(session_data)
    if now is not None:
        return SessionView(session, Config(), now=now)
    return SessionView(session, Config())


def test_empty_transcript_path_returns_empty_string() -> None:
    view = _view_with_transcript('')
    assert view.elapsed == ''


def test_missing_transcript_file_returns_empty_string(tmp_path: Path) -> None:
    view = _view_with_transcript(str(tmp_path / 'nonexistent.jsonl'))
    assert view.elapsed == ''


def test_five_minutes_old_transcript(tmp_path: Path) -> None:
    transcript = tmp_path / 'transcript.jsonl'
    transcript.write_text('{}')
    now = time.time()
    five_min_ago = now - 300
    os.utime(transcript, (five_min_ago, five_min_ago))
    view = _view_with_transcript(str(transcript), now=now)
    assert view.elapsed == '5m'


def test_two_hours_two_minutes_old_transcript(tmp_path: Path) -> None:
    transcript = tmp_path / 'transcript.jsonl'
    transcript.write_text('{}')
    now = time.time()
    old_mtime = now - 7320  # 2h 2m
    os.utime(transcript, (old_mtime, old_mtime))
    view = _view_with_transcript(str(transcript), now=now)
    assert view.elapsed == '2h2m'
