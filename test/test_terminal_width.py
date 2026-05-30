'''Tests for terminal_width() source ordering (Audit WIDTH-1 / PERF-TMUX):
COLUMNS (which Claude Code sets to the real allocated width) is authoritative and
consulted first; the tmux probe is bounded by a timeout and never hangs/crashes.'''
import subprocess

import statusline_command as sl


def _no_tmux(monkeypatch):
    monkeypatch.delenv('TMUX_PANE', raising=False)
    monkeypatch.delenv('TMUX', raising=False)


def test_columns_wins_over_width_file(monkeypatch, tmp_home):
    # WIDTH-1: a stale terminal-width file must NOT override the authoritative
    # COLUMNS that Claude Code sets.
    (tmp_home / '.claude').mkdir(parents=True, exist_ok=True)
    (tmp_home / '.claude' / 'terminal-width').write_text('70')
    _no_tmux(monkeypatch)
    monkeypatch.setenv('COLUMNS', '95')
    assert sl.terminal_width() == 95


def test_width_file_used_when_columns_absent(monkeypatch, tmp_home):
    (tmp_home / '.claude').mkdir(parents=True, exist_ok=True)
    (tmp_home / '.claude' / 'terminal-width').write_text('70')
    _no_tmux(monkeypatch)
    monkeypatch.delenv('COLUMNS', raising=False)
    assert sl.terminal_width() == 70


def test_columns_consulted_before_tmux(monkeypatch, tmp_home):
    # With COLUMNS set, the tmux subprocess must not even be invoked.
    monkeypatch.setenv('COLUMNS', '111')
    monkeypatch.setenv('TMUX_PANE', '%0')

    def _boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError('tmux probe ran despite COLUMNS being set')

    monkeypatch.setattr(sl.subprocess, 'run', _boom)
    assert sl.terminal_width() == 111


def test_tmux_timeout_is_caught(monkeypatch, tmp_home):
    # PERF-TMUX: a wedged tmux server raises TimeoutExpired; terminal_width must
    # swallow it (SubprocessError) and fall through, never propagate/hang.
    monkeypatch.delenv('COLUMNS', raising=False)
    monkeypatch.setenv('TMUX_PANE', '%0')
    (tmp_home / '.claude').mkdir(parents=True, exist_ok=True)
    (tmp_home / '.claude' / 'terminal-width').write_text('64')

    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd='tmux', timeout=0.2)

    monkeypatch.setattr(sl.subprocess, 'run', _timeout)
    assert sl.terminal_width() == 64  # falls through to the width file, no crash


def test_tmux_probe_passes_timeout(monkeypatch, tmp_home):
    # The tmux subprocess.run call must carry a bounded timeout kwarg.
    monkeypatch.delenv('COLUMNS', raising=False)
    monkeypatch.setenv('TMUX_PANE', '%0')

    class _Result:
        stdout = '88'

    captured = {}

    def _run(*a, **k):
        captured.update(k)
        return _Result()

    monkeypatch.setattr(sl.subprocess, 'run', _run)
    assert sl.terminal_width() == 88
    assert isinstance(captured.get('timeout'), (int, float)) and captured['timeout'] > 0
