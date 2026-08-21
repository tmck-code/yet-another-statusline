"""Tests for terminal_width() probe order and tmux timeout behaviour."""

from __future__ import annotations
import subprocess
from unittest.mock import MagicMock, patch

import yas.constants as constants
from yas.render.text import terminal_width


def test_columns_env_returned_immediately(monkeypatch):
    monkeypatch.setenv('COLUMNS', '160')
    # Ensure TMUX_PANE is absent so tmux would only be attempted if COLUMNS
    # is not picked up first.
    monkeypatch.delenv('TMUX_PANE', raising=False)

    with patch('subprocess.run') as mock_run:
        result = terminal_width()
        mock_run.assert_not_called()

    assert result == 160


def test_tmux_returns_width_when_columns_absent(monkeypatch):
    monkeypatch.delenv('COLUMNS', raising=False)
    monkeypatch.setenv('TMUX_PANE', '%1')

    fake_result = MagicMock()
    fake_result.stdout = "'120'\n"

    with patch('subprocess.run', return_value=fake_result) as mock_run:
        result = terminal_width()

    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs.get('timeout') == 0.2 or (
        len(call_kwargs.args) > 1 and call_kwargs.args[1].get('timeout') == 0.2
    ), 'subprocess.run must be called with timeout=0.2'
    assert result == 120


def test_tmux_timeout_falls_through_without_raising(monkeypatch, tmp_path):
    monkeypatch.delenv('COLUMNS', raising=False)
    monkeypatch.setenv('TMUX_PANE', '%1')

    # Patch CLAUDE_DIR so the file fallback reads a known value.
    with patch('yas.constants.CLAUDE_DIR', tmp_path):
        width_file = constants.terminal_width_path()
        width_file.parent.mkdir(parents=True, exist_ok=True)
        width_file.write_text('88\n')

        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(['tmux'], 0.2)):
            result = terminal_width()

    # Must not raise; should fall through to the file fallback.
    assert result == 88


def test_columns_zero_falls_through(monkeypatch, tmp_path):
    monkeypatch.setenv('COLUMNS', '0')
    monkeypatch.delenv('TMUX_PANE', raising=False)

    # Make the tmux probe fail with KeyError (no TMUX_PANE) and the file
    # fallback return a value so we can confirm fall-through happened.
    with patch('yas.constants.CLAUDE_DIR', tmp_path):
        width_file = constants.terminal_width_path()
        width_file.parent.mkdir(parents=True, exist_ok=True)
        width_file.write_text('77\n')

        result = terminal_width()

    assert result == 77
