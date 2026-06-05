"""Tests for SessionView.elapsed (total_duration_ms-based elapsed formatting)."""
import json
from pathlib import Path

from yas.config import Config
from yas.info import SessionView
from yas.session import SessionInfo

SESSION_FILE = Path(__file__).parent.parent / 'ops' / 'session-info-example.json'


def _view_with_duration_ms(total_duration_ms: int) -> SessionView:
    session_data = json.loads(SESSION_FILE.read_text())
    session_data['costUSD'] = session_data.get('costUSD', 0.0)
    # Inject the desired duration into the cost block.
    if 'cost' not in session_data:
        session_data['cost'] = {}
    session_data['cost']['total_duration_ms'] = total_duration_ms
    session = SessionInfo.from_dict(session_data)
    return SessionView(session, Config())


def test_zero_duration_returns_empty_string() -> None:
    """total_duration_ms=0 → elapsed is empty string."""
    view = _view_with_duration_ms(0)
    assert view.elapsed == ''


def test_five_minutes_duration() -> None:
    """total_duration_ms=300000 (5 minutes) → elapsed == '5m'."""
    view = _view_with_duration_ms(300_000)
    assert view.elapsed == '5m'


def test_two_hours_two_minutes_duration() -> None:
    """total_duration_ms=7320000 (2h2m) → elapsed == '2h2m'."""
    view = _view_with_duration_ms(7_320_000)
    assert view.elapsed == '2h2m'


def test_elapsed_reads_from_payload_not_filesystem() -> None:
    """elapsed comes from payload total_duration_ms, regardless of transcript path."""
    from unittest.mock import patch

    session_data = json.loads(SESSION_FILE.read_text())
    session_data['transcript_path'] = ''   # no transcript
    if 'cost' not in session_data:
        session_data['cost'] = {}
    session_data['cost']['total_duration_ms'] = 600_000  # 10 minutes
    session = SessionInfo.from_dict(session_data)
    view = SessionView(session, Config())

    with patch('pathlib.Path.stat', side_effect=AssertionError('unexpected Path.stat call')):
        result = view.elapsed

    assert result == '10m'
