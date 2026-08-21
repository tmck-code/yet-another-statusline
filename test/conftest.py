import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from helper import strip_ansi as _strip_ansi
import yas.constants as _sl_constants
import yas.renderer as _sl_renderer
import yas.render.gradient as _sl_gradient
import yas.session as _sl_session
import yas.info.subagents as _sl_subagents
import yas.info.tasks as _sl_tasks
import yas.info.skills as _sl_skills
import yas.info.openspec as _sl_openspec

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
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> float:
    """Freeze every live clock the render path reads — for byte-identity tests.

    Two back-to-back renders of the same state are otherwise not byte-equal:
    `rainbow_step` (`int(time.time()) % len(RAINBOW_PALETTE)`) rolls the border
    palette on any second boundary, and `Renderer.task_row`'s elapsed timer can
    flip digit width (`9:59` -> `10:00`), which the content-sized plan column
    then propagates into the layout. Shim each module's own `time` reference
    rather than the stdlib, so nothing outside the render path sees a stopped
    clock. Pass the returned instant to `SessionView(..., now)` — that is the
    third live-clock seam.
    """
    now   = time.time()
    clock = SimpleNamespace(time=lambda: now)
    monkeypatch.setattr(_sl_renderer, 'time', clock)
    monkeypatch.setattr(_sl_gradient, 'time', clock)
    return now


@pytest.fixture
def silence_dynamic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every conditional (dynamic) section so token stats render deterministically.

    Each dynamic section reads the real machine (transcript, ~/.claude/settings.json,
    the cwd's openspec dir, the wall-clock rainbow step, ...). Left alone, the host's
    own plugins/skills/tasks and clock leak in and synthesise an extra dynamic
    row/seam or break byte-for-byte comparison, so neutralise every source —
    including Workspace.plugins, which reads CLAUDE_DIR/settings.json directly.
    `**kwargs` on every patched classmethod tolerates each real signature
    (RunningSubagents.from_session takes `now=`/`cache=`) without pinning to it.
    """
    monkeypatch.setenv('YAS_RAINBOW_STEP', '0')
    monkeypatch.setattr(_sl_subagents.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir, **kwargs: _sl_subagents.RunningSubagents(subagents=[])))
    monkeypatch.setattr(_sl_tasks.TaskList, 'from_session',
                        classmethod(lambda cls, path, **kwargs: _sl_tasks.TaskList(tasks=[], last_event_ts=0.0)))
    monkeypatch.setattr(_sl_skills.LoadedSkills, 'from_transcript',
                        classmethod(lambda cls, path, **kwargs: _sl_skills.LoadedSkills(names=[])))
    monkeypatch.setattr(_sl_openspec.OpenSpec, 'from_cwd',
                        classmethod(lambda cls, cwd, max_depth=None, **kwargs: _sl_openspec.OpenSpec(changes=[])))
    monkeypatch.setattr(_sl_session.Workspace, 'plugins', property(lambda self: ''))


@pytest.fixture
def tmp_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    # One patch point, by design: every YAS path is a *function* in
    # yas.constants (tokens_log(), config_path(), ...) that reads the
    # module-global CLAUDE_DIR when called, not a Path frozen at import. Modules
    # import those helpers rather than CLAUDE_DIR itself, so rebinding the single
    # constant here redirects every read and write in the process — including
    # modules imported long before this fixture runs. Adding a new module that
    # touches disk no longer requires touching this fixture; it only has to go
    # through yas.constants like everything else.
    claude_dir = tmp_path / '.claude'
    monkeypatch.setattr(_sl_constants, 'CLAUDE_DIR', claude_dir)
    return tmp_path
