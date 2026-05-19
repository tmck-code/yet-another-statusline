import importlib.util
import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import shim: load claude/statusline-command.py under a stable module name
# ---------------------------------------------------------------------------
_SRC = Path(__file__).resolve().parent.parent / 'claude' / 'statusline-command.py'

if 'statusline_command' not in sys.modules:
    _spec = importlib.util.spec_from_file_location('statusline_command', _SRC)
    _mod  = importlib.util.module_from_spec(_spec)
    sys.modules['statusline_command'] = _mod
    _spec.loader.exec_module(_mod)

import statusline_command as sl  # noqa: E402

# ---------------------------------------------------------------------------
# ANSI-stripping helper
# ---------------------------------------------------------------------------
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub('', s)


@pytest.fixture(name='strip_ansi')
def strip_ansi_fixture():
    return strip_ansi


# ---------------------------------------------------------------------------
# tmp_home: redirect sl.HOME to tmp_path so tests never touch the real $HOME
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sl, 'HOME', tmp_path)
    return tmp_path
