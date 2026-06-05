"""Tests for terminal_width() probe order and tmux timeout behaviour."""

from __future__ import annotations
import subprocess
from unittest.mock import MagicMock, patch

from yas.render.text import terminal_width


# ---------------------------------------------------------------------------
# Scenario 3.1 — COLUMNS=160 is returned immediately; tmux is never called
# ---------------------------------------------------------------------------

def test_columns_env_returned_immediately(monkeypatch):
    monkeypatch.setenv('COLUMNS', '160')
    # Ensure TMUX_PANE is absent so tmux would only be attempted if COLUMNS
    # is not picked up first.
    monkeypatch.delenv('TMUX_PANE', raising=False)

    with patch('subprocess.run') as mock_run:
        result = terminal_width()
        mock_run.assert_not_called()

    assert result == 160


# ---------------------------------------------------------------------------
# Scenario 3.2 — COLUMNS not set, tmux responds with 120 within timeout
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Scenario 3.3 — tmux subprocess times out; function continues to next source
# ---------------------------------------------------------------------------

def test_tmux_timeout_falls_through_without_raising(monkeypatch, tmp_path):
    monkeypatch.delenv('COLUMNS', raising=False)
    monkeypatch.setenv('TMUX_PANE', '%1')

    # Patch CLAUDE_DIR so the file fallback reads a known value.
    width_file = tmp_path / 'terminal-width'
    width_file.write_text('88\n')

    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(['tmux'], 0.2)):
        with patch('yas.render.text.CLAUDE_DIR', tmp_path):
            result = terminal_width()

    # Must not raise; should fall through to the file fallback.
    assert result == 88


# ---------------------------------------------------------------------------
# Scenario 3.4 — COLUMNS=0 is treated as absent; falls through to next source
# ---------------------------------------------------------------------------

def test_columns_zero_falls_through(monkeypatch, tmp_path):
    monkeypatch.setenv('COLUMNS', '0')
    monkeypatch.delenv('TMUX_PANE', raising=False)

    # Make the tmux probe fail with KeyError (no TMUX_PANE) and the file
    # fallback return a value so we can confirm fall-through happened.
    width_file = tmp_path / 'terminal-width'
    width_file.write_text('77\n')

    with patch('yas.render.text.CLAUDE_DIR', tmp_path):
        result = terminal_width()

    assert result == 77
