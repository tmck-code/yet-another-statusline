import os
import subprocess
from pathlib import Path
from typing import Callable

import pytest

from helper import strip_ansi as _strip_ansi
import yas.app as _sl_app
import yas.config as _sl_config
import yas.constants as _sl_constants
import yas.session as _sl_session
import yas.info.subagents as _sl_subagents
import yas.info.workflows as _sl_workflows
import yas.tokens as _sl_tokens

_SRC = Path(__file__).resolve().parent.parent / 'claude' / 'statusline_command.py'


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
    # CLAUDE_DIR is a module-level constant frozen at import as HOME/'.claude'.
    # Patching HOME alone leaves it pointing at the real ~/.claude, so source
    # reads (token logs, subagents, theme, settings) would escape the sandbox.
    # Patch each package module that carries its own copy.
    claude_dir = tmp_path / '.claude'
    monkeypatch.setattr(_sl_app,       'CLAUDE_DIR', claude_dir)
    monkeypatch.setattr(_sl_config,    'CLAUDE_DIR', claude_dir)
    monkeypatch.setattr(_sl_constants, 'CLAUDE_DIR', claude_dir)
    monkeypatch.setattr(_sl_session,   'CLAUDE_DIR', claude_dir)
    monkeypatch.setattr(_sl_subagents, 'CLAUDE_DIR', claude_dir)
    monkeypatch.setattr(_sl_workflows, 'CLAUDE_DIR', claude_dir)
    monkeypatch.setattr(_sl_tokens,    'CLAUDE_DIR', claude_dir)
    return tmp_path
