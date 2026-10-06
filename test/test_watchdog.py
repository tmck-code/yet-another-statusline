'''The watchdog bounds a statusline/hook process whose stdin is never closed.

Regression for orphaned renders on Windows: Claude Code kills the bash.exe
wrapper but keeps the stdin pipe open, leaving python blocked in
sys.stdin.read() for the life of the session.
'''
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from yas.constants import WATCHDOG_SECONDS

_ROOT        = Path(__file__).resolve().parent.parent
_ENTRY       = _ROOT / 'claude' / 'statusline_command.py'
_HOOK_SCRIPT = _ROOT / 'hooks' / 'yas-prompt-hook.py'

# Shrinks every Timer the script arms to 0.3 s, then runs it as __main__, so
# the real entry-point wiring is under test rather than a re-implementation.
_RUNNER = '''
import runpy, sys, threading
_Timer = threading.Timer
threading.Timer = lambda _s, fn, args=(): _Timer(0.3, fn, args)
sys.path.insert(0, sys.argv[2])
runpy.run_path(sys.argv[1], run_name='__main__')
sys.exit(7)
'''


def _run_with_open_stdin(script: Path, tmp_path: Path) -> int:
    '''Run `script` with a stdin pipe that is never written or closed; return its exit code.'''
    claude_dir = tmp_path / '.claude'
    env = {**os.environ, 'HOME': str(tmp_path), 'USERPROFILE': str(tmp_path),
           'CLAUDE_CONFIG_DIR': str(claude_dir)}
    proc = subprocess.Popen(
        [sys.executable, '-c', _RUNNER, str(script), str(_ROOT / 'claude')],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )
    try:
        return proc.wait(timeout=WATCHDOG_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail(f'{script.name} still blocked on stdin after {WATCHDOG_SECONDS}s')
    finally:
        assert proc.stdin is not None
        proc.stdin.close()


def test_statusline_entry_exits_when_stdin_never_closes(tmp_path):
    assert _run_with_open_stdin(_ENTRY, tmp_path) == 0


def test_prompt_hook_exits_when_stdin_never_closes(tmp_path):
    assert _run_with_open_stdin(_HOOK_SCRIPT, tmp_path) == 0


def test_prompt_hook_watchdog_matches_constant():
    spec = importlib.util.spec_from_file_location('_yas_prompt_hook_wd', _HOOK_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._WATCHDOG_SECONDS == WATCHDOG_SECONDS
