import re
import time

import pytest

import yas.layout as layout
from helper import strip_ansi
from yas.config import Config, CpuConfig, ElapsedConfig, MemoryConfig, ShellCommandsConfig
from yas.constants import ICON_TERMINAL, SHELL_BG_LABEL, SHELL_FG_LABEL
from yas.info import SessionView
from yas.info.shell_commands import RunningShellCommands
from yas.info.tasks import Task, TaskList
from yas.render.text import _visible_width
from yas.renderer import Renderer
from yas.tokens import TickRecord, TokenLog

WIDTHS = (80, 140)
DEFAULT_COMMAND_SPECS = (
    ('uv run pytest -q', {}),
    ('make demo/img', {'background': False, 'elapsed': 8}),
    ('tail -f /tmp/server.log', {'elapsed': 840}),
)


@pytest.fixture
def default_cmds(make_shell_command):
    return tuple(make_shell_command(command, **kw) for command, kw in DEFAULT_COMMAND_SPECS)


@pytest.fixture
def setup(make_view, make_subagent, default_cmds):
    def make(
        *, subs: int = 2, cmds=None, labels: bool = False, activity: str = 'pytest', **cfg_kw,
    ) -> SessionView:
        sub_list = [
            make_subagent(f'agent{i}', activity=activity, start_ago=10, mtime_ago=5)
            for i in range(subs)
        ]
        return make_view(
            cfg      = Config(labels=labels, shell_commands=ShellCommandsConfig(**cfg_kw)),
            subs     = sub_list,
            commands = default_cmds if cmds is None else tuple(cmds),
        )
    return make


def _build(view: SessionView, width: int, renderer: Renderer) -> layout.LayoutSpec:
    tick = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    if width >= 120:
        return layout.build_wide(view, tick, width, renderer)
    return layout.build_narrow(view, width, renderer)


def _plain(spec: layout.LayoutSpec) -> list[str]:
    return [strip_ansi(row.content) for row in spec.rows if row.kind == 'content']


def _rendered(view: SessionView, width: int, renderer: Renderer) -> list[str]:
    return [strip_ansi(line) for line in layout.render_layout(_build(view, width, renderer), renderer)]


_MAIN_ROW_RE = re.compile(r'\d+:\d\d\s+main\b')


def _has_main_row(lines: list[str]) -> bool:
    'True when a row is the synthetic main row: its name field reads `main`.'
    return any(_MAIN_ROW_RE.search(line) for line in lines)


# --- Renderer helper units (still supported by style = "agents") ------------

def test_command_rows_mark_background_and_foreground(renderer, make_shell_command) -> None:
    sc = RunningShellCommands(commands=(
        make_shell_command('bg-cmd'),
        make_shell_command('fg-cmd', background=False),
    ))
    rows = [strip_ansi(line) for line in renderer.shell_commands_side(sc, ShellCommandsConfig())]
    assert any(row.lstrip().startswith(f'{SHELL_BG_LABEL}  bg-cmd') for row in rows)
    assert any(row.lstrip().startswith(f'{SHELL_FG_LABEL}  fg-cmd') for row in rows)


@pytest.mark.parametrize('inner', (40, 76, 136))
def test_list_lines_all_match_inner_width(inner: int, renderer, default_cmds) -> None:
    cfg = ShellCommandsConfig(max_items=2)
    sc = RunningShellCommands(commands=default_cmds)
    lines = renderer.shell_commands_list(sc, cfg, inner)
    assert any('+1 more' in strip_ansi(line) for line in lines)
    assert {_visible_width(line) for line in lines} == {inner}


def test_badge_omits_hidden_fields(renderer, setup) -> None:
    view = setup(elapsed=ElapsedConfig(enabled=False),
                  cpu=CpuConfig(enabled=False), memory=MemoryConfig(enabled=False))
    badge = strip_ansi(renderer.shell_commands_badge(view.shell_commands, view.cfg.shell_commands))
    assert badge == f'{ICON_TERMINAL} 3'


@pytest.mark.parametrize('seconds', (7, 72, 599, 600, 840, 3599, 3600, 3725))
def test_shell_elapsed_matches_shared_duration_format(seconds: int, renderer, make_shell_command) -> None:
    from yas.render.tasks_view import fmt_duration
    cfg = ShellCommandsConfig(cpu=CpuConfig(enabled=False), memory=MemoryConfig(enabled=False))
    sc = RunningShellCommands(commands=(make_shell_command('a', elapsed=seconds), make_shell_command('b', elapsed=1)))
    side = [strip_ansi(line) for line in renderer.shell_commands_side(sc, cfg)]
    assert side[1].rstrip().endswith(fmt_duration(seconds))
    assert len({len(line) for line in side}) == 1
    badge = strip_ansi(renderer.shell_commands_badge(sc, cfg))
    assert badge.endswith(fmt_duration(seconds)) or fmt_duration(seconds) in badge


# --- The standalone section is suppressed in regular layouts ----------------

@pytest.mark.parametrize('position', ('right', 'below'))
@pytest.mark.parametrize('subs', (0, 2))
@pytest.mark.parametrize('width', (80, 140, 200))
def test_standalone_shell_section_suppressed_in_regular_layouts(
    width: int, subs: int, position: str, renderer, setup,
) -> None:
    lines = _rendered(setup(subs=subs, position=position), width, renderer)
    assert {_visible_width(line) for line in lines} == {width}
    assert not any(ICON_TERMINAL in line or 'shell commands' in line for line in lines)
    assert _has_main_row(lines)


@pytest.mark.parametrize('position', ('right', 'below'))
@pytest.mark.parametrize('width', WIDTHS)
def test_badge_style_draws_no_badge_rows(width: int, position: str, renderer, setup) -> None:
    plain = _plain(_build(setup(position=position), width, renderer))
    assert not any(ICON_TERMINAL in row for row in plain)
    assert _has_main_row(plain)


@pytest.mark.parametrize('width', WIDTHS)
def test_list_style_draws_no_command_rows(width: int, renderer, setup) -> None:
    plain = _plain(_build(setup(style='list', position='below'), width, renderer))
    assert not any('shell commands (3)' in row for row in plain)
    assert not any(row.lstrip().startswith(('bg  ', 'fg  ')) for row in plain)
    assert _has_main_row(plain)


@pytest.mark.parametrize('width', WIDTHS)
def test_no_subagents_draws_main_row_only(width: int, renderer, setup) -> None:
    lines = _rendered(setup(subs=0), width, renderer)
    assert sum(bool(_MAIN_ROW_RE.search(line)) for line in lines) == 1
    assert not any('agent' in line for line in lines)
    assert not any(ICON_TERMINAL in line or 'shell commands' in line for line in lines)


@pytest.mark.parametrize('position', ('right', 'below'))
def test_shell_disabled_still_draws_main_row(position: str, renderer, setup) -> None:
    plain = _plain(_build(setup(subs=0, enabled=False, position=position), 140, renderer))
    assert _has_main_row(plain)
    assert not any(ICON_TERMINAL in row or 'shell commands' in row for row in plain)


@pytest.mark.parametrize('position,subs', (('right', 2), ('below', 2), ('below', 0)))
@pytest.mark.parametrize('width', (140, 200))
def test_regular_layout_rows_share_visible_width(
    width: int, position: str, subs: int, renderer, setup,
) -> None:
    lines = _rendered(setup(subs=subs, style='list', position=position, labels=True), width, renderer)
    assert {_visible_width(line) for line in lines} == {width}


def test_main_row_sits_beside_a_plan_and_subagents(renderer, setup) -> None:
    view = setup()
    now = time.time()
    view.__dict__['tasks'] = TaskList(
        tasks=[Task(id=1, subject='plan item', active_form='doing plan item',
                    status='in_progress', started_at=now - 10)],
        last_event_ts=now - 5,
    )
    lines = _rendered(view, 140, renderer)
    assert {_visible_width(line) for line in lines} == {140}
    assert _has_main_row(lines)
    assert not any(ICON_TERMINAL in line or 'shell commands' in line for line in lines)
