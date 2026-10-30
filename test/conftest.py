import json
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
from yas.config import Config
from yas.info import SessionView
from yas.info.main_activity import MainActivity
from yas.info.subagents import RunningSubagent, RunningSubagents
from yas.info.shell_commands import RunningShellCommands, ShellCommand
from yas.renderer import Renderer
from yas.session import SessionInfo

_SRC = Path(__file__).resolve().parent.parent / 'claude' / 'statusline_command.py'
EXAMPLE_SESSION = Path(__file__).resolve().parent.parent / 'ops' / 'session-info-example.json'


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    'Drop GIT_* vars that git exports to hooks (GIT_DIR, GIT_INDEX_FILE, ...) so tests never touch the real repo.'
    for key in [k for k in os.environ if k.startswith('GIT_')]:
        monkeypatch.delenv(key)


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


@pytest.fixture
def example_session() -> SessionInfo:
    'The checked-in example payload, pointed at an existing transcript so gather runs.'
    session = SessionInfo.from_dict(json.loads(EXAMPLE_SESSION.read_text()))
    session.transcript_path = str(EXAMPLE_SESSION)
    return session


@pytest.fixture
def renderer() -> Renderer:
    return Renderer()


@pytest.fixture
def make_shell_command() -> Callable[..., ShellCommand]:
    def make(
        command: str, *,
        background: bool = True,
        elapsed: float = 72,
        cpu: float | None = 5.0,
        rss_kb: int = 20 * 1024,
        pid: int = 1,
        display_command: str = '',
        live_command: str = '',
    ) -> ShellCommand:
        return ShellCommand(
            pid=pid, command=command, background=background, elapsed_s=elapsed,
            cpu_percent=cpu, rss_kb=rss_kb, display_command=display_command,
            live_command=live_command,
        )
    return make


@pytest.fixture
def make_subagent() -> Callable[..., RunningSubagent]:
    def make(
        agent_type: str, *,
        now: float | None = None,
        agent_id: str | None = None,
        description: str = 'test desc',
        billed_in: int = 1000,
        output: int = 100,
        first_timestamp: float | None = None,
        start_ago: float = 120,
        model: str = 'claude-sonnet-4-6',
        cache_read_in: int = 0,
        total_input: int = 1000,
        last_activity: tuple[str, str, dict[str, object]] | None = None,
        last_activity_ts: float | None = None,
        thinking_s: float | None = None,
        activity: str | None = None,
        mtime: float | None = None,
        mtime_ago: float = 2,
        end_ts: float = 0.0,
        parent_id: str = '',
        spawn_depth: int = 0,
        status: str = 'running',
        run_count: int = 0,
        is_fork: bool = False,
        resumed: bool = False,
        run_start_ts: float | None = None,
        bash_inflight: tuple[tuple[str, float], ...] = (),
        commands: tuple[tuple[str, float], ...] = (),
        jsonl_path: str = '',
    ) -> RunningSubagent:
        base = time.time() if now is None else now
        if last_activity is None:
            if thinking_s is not None:
                last_activity = ('thinking', '', {})
            elif activity is not None:
                last_activity = ('tool_use', 'Bash', {'command': activity})
            else:
                last_activity = ('tool_use', 'Read', {})
        if last_activity_ts is None:
            last_activity_ts = base - thinking_s if thinking_s is not None else 0.0
        if commands:
            bash_inflight = tuple((command, base - ago) for command, ago in commands)
        return RunningSubagent(
            agent_type       = agent_type,
            description      = description,
            billed_in        = billed_in,
            output           = output,
            first_timestamp  = base - start_ago if first_timestamp is None else first_timestamp,
            model            = model,
            cache_read_in    = cache_read_in,
            total_input      = total_input,
            last_activity    = last_activity,
            end_ts           = end_ts,
            mtime            = base - mtime_ago if mtime is None else mtime,
            agent_id         = agent_id or f'agent-{agent_type}',
            jsonl_path       = jsonl_path,
            parent_id        = parent_id,
            spawn_depth      = spawn_depth,
            status           = status,
            run_count        = run_count,
            is_fork          = is_fork,
            resumed          = resumed,
            run_start_ts     = run_start_ts,
            bash_inflight    = bash_inflight,
            last_activity_ts = last_activity_ts,
        )
    return make


@pytest.fixture
def make_view(
    monkeypatch: pytest.MonkeyPatch, example_session: SessionInfo,
) -> Callable[..., SessionView]:
    'A SessionView whose subagent and shell gathers return the supplied fixtures.'
    def make(
        *,
        cfg: Config | None = None,
        subs: list[RunningSubagent] | None = None,
        commands: tuple[ShellCommand, ...] = (),
        now: float | None = None,
        main_activity: MainActivity | None = None,
        subagents_from_session: Callable[..., RunningSubagents] | None = None,
        shell_from_session: Callable[..., RunningShellCommands] | None = None,
    ) -> SessionView:
        subagent_list = list(subs or ())
        subagent_gather = subagents_from_session or (
            lambda cls, sid, pdir, **kw: RunningSubagents(subagents=subagent_list)
        )
        shell_gather = shell_from_session or (
            lambda cls, *a, **kw: RunningShellCommands(commands=commands)
        )
        monkeypatch.setattr(RunningSubagents, 'from_session', classmethod(subagent_gather))
        monkeypatch.setattr(RunningShellCommands, 'from_session', classmethod(shell_gather))
        view = SessionView(example_session, cfg or Config(), now=now)
        if main_activity is not None:
            view.__dict__['main_activity'] = main_activity
        return view
    return make
