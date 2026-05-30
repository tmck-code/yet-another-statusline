import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest

from helper import strip_ansi as _strip_ansi

_SRC = Path(__file__).resolve().parent.parent / 'claude' / 'statusline_command.py'

if 'statusline_command' not in sys.modules:
    _spec = importlib.util.spec_from_file_location('statusline_command', _SRC)
    assert _spec is not None and _spec.loader is not None
    _mod  = importlib.util.module_from_spec(_spec)
    sys.modules['statusline_command'] = _mod
    _spec.loader.exec_module(_mod)



def _hooks_active() -> bool:
    'True if core.hooksPath points at the committed hooks (or git is unavailable — then stay quiet).'
    try:
        result = subprocess.run(
            ['git', 'config', '--local', '--get', 'core.hooksPath'],
            cwd            = _SRC.parent.parent,
            capture_output = True,
            text           = True,
        )
    except OSError:
        return True
    return result.stdout.strip() == '.github/hooks'


def pytest_report_header(config: pytest.Config) -> str | None:
    'Nudge contributors to enable the pre-commit hook, unless on CI or an xdist worker.'
    if hasattr(config, 'workerinput') or os.environ.get('CI') or _hooks_active():
        return None
    return 'NOTE: git pre-commit hooks not active — run `make hooks` (CI runs the same checks on push)'


@pytest.fixture(name='strip_ansi')
def strip_ansi_fixture() -> Callable[[str], str]:
    return _strip_ansi


@pytest.fixture
def tmp_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    # HOME / CLAUDE_DIR live in statusline.config (the canonical single source
    # so every reader across every module sees the patched value via dynamic
    # `config.X` attribute access). Patching `sl.X` would only reach refs that
    # bound the name at import — none do now.
    from statusline import config
    monkeypatch.setattr(config, 'HOME', tmp_path)
    monkeypatch.setattr(config, 'CLAUDE_DIR', tmp_path / '.claude')
    return tmp_path
