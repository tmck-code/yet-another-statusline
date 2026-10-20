import json
import re
import time
from pathlib import Path

import pytest

import yas.info.subagents as subagents_mod
import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
from helper import strip_ansi
from yas.config import Config, CpuConfig, ElapsedConfig, MemoryConfig, ShellCommandsConfig
from yas.constants import CLR_WARN, ICON_TERMINAL
from yas.info import SessionView
from yas.info.shell_commands import RunningShellCommands, ShellCommand
from yas.render.text import _visible_width
from yas.tokens import TickRecord, TokenLog

_r = renderer_mod.Renderer()
SESSION = Path(__file__).parent.parent / 'ops' / 'session-info-example.json'
WIDTHS = (80, 140)


def _sub(agent_type: str, activity: str = 'pytest') -> subagents_mod.RunningSubagent:
    now = time.time()
    return subagents_mod.RunningSubagent(
        agent_type      = agent_type,
        description     = 'test desc',
        billed_in       = 1000,
        output          = 100,
        first_timestamp = now - 10,
        model           = 'claude-sonnet-4-6',
        cache_read_in   = 0,
        total_input     = 1000,
        last_activity   = ('tool_use', 'Bash', {'command': activity}),
        mtime           = now - 5,
    )


def _cmd(command: str, *, bg: bool = True, elapsed: float = 72, cpu: float | None = 5.0,
         rss_kb: int = 20 * 1024) -> ShellCommand:
    return ShellCommand(pid=1, command=command, background=bg, elapsed_s=elapsed,
                        cpu_percent=cpu, rss_kb=rss_kb)


DEFAULT_CMDS = (
    _cmd('uv run pytest -q'),
    _cmd('make demo/img', bg=False, elapsed=8),
    _cmd('tail -f /tmp/server.log', elapsed=840),
)


def _setup(monkeypatch: pytest.MonkeyPatch, *, subs: int = 2, cmds=DEFAULT_CMDS, labels: bool = False, activity: str = 'pytest', **cfg_kw) -> SessionView:
    sub_list = [_sub(f'agent{i}', activity) for i in range(subs)]
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir, **kw: subagents_mod.RunningSubagents(subagents=sub_list)),
    )
    monkeypatch.setattr(
        RunningShellCommands, 'from_session',
        classmethod(lambda cls, *a, **kw: RunningShellCommands(commands=tuple(cmds))),
    )
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    session.transcript_path = str(SESSION)  # an existing file, so the gather is attempted
    return SessionView(session, Config(labels=labels, shell_commands=ShellCommandsConfig(**cfg_kw)))


def _build(view: SessionView, width: int) -> layout.LayoutSpec:
    tick = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    if width >= 120:
        return layout.build_wide(view, tick, width, _r)
    return layout.build_narrow(view, width, _r)


def _plain(spec: layout.LayoutSpec) -> list[str]:
    return [strip_ansi(row.content) for row in spec.rows if row.kind == 'content']


@pytest.mark.parametrize('width', WIDTHS)
def test_badge_on_first_subagent_row_only(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    spec = _build(_setup(monkeypatch), width)
    with_badge = [p for p in _plain(spec) if ICON_TERMINAL in p]
    assert len(with_badge) == 1
    assert 'agent0' in with_badge[0]
    assert '14:00' in with_badge[0]


@pytest.mark.parametrize('width', WIDTHS)
def test_badge_without_subagents_is_own_row(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    spec = _build(_setup(monkeypatch, subs=0), width)
    rows = [p for p in _plain(spec) if ICON_TERMINAL in p]
    assert len(rows) == 1
    assert rows[0].strip().startswith(ICON_TERMINAL)


@pytest.mark.parametrize('width', WIDTHS)
def test_list_has_header_and_one_row_per_command(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    plain = _plain(_build(_setup(monkeypatch, style='list', position='below'), width))
    assert any('shell commands (3)' in p for p in plain)
    assert any(p.lstrip().startswith('bg  uv run pytest -q') and p.rstrip(' │').rstrip().endswith('1:12') for p in plain)
    assert any(p.lstrip().startswith('fg  make demo/img') and p.rstrip(' │').rstrip().endswith('0:08') for p in plain)
    assert not any(ICON_TERMINAL in p and 'agent' in p for p in plain)


@pytest.mark.parametrize('width', WIDTHS)
def test_list_without_subagents_still_renders(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    plain = _plain(_build(_setup(monkeypatch, subs=0, style='list', position='below'), width))
    assert any('shell commands (3)' in p for p in plain)


def test_list_truncates_command_with_ellipsis(monkeypatch: pytest.MonkeyPatch) -> None:
    cmds = (_cmd('x' * 80),)
    plain = _plain(_build(_setup(monkeypatch, cmds=cmds, style='list', position='below', max_command_width=20), 140))
    row = next(p for p in plain if p.lstrip().startswith('bg'))
    assert 'x' * 39 + '…' in row  # the list closed by a divider may grow to twice max_command_width
    assert 'x' * 40 not in row


def test_list_caps_at_max_items_with_more_row(monkeypatch: pytest.MonkeyPatch) -> None:
    cmds = tuple(_cmd(f'cmd{i}') for i in range(5))
    plain = _plain(_build(_setup(monkeypatch, cmds=cmds, style='list', position='below', max_items=2), 80))
    assert sum(p.lstrip().startswith('bg') for p in plain) == 2
    assert any('+3 more' in p for p in plain)


@pytest.mark.parametrize('position', ('right', 'below'))
def test_hidden_when_no_commands(monkeypatch: pytest.MonkeyPatch, position: str) -> None:
    plain = _plain(_build(_setup(monkeypatch, cmds=(), position=position), 80))
    assert not any(ICON_TERMINAL in p or 'shell commands' in p for p in plain)


@pytest.mark.parametrize('position', ('right', 'below'))
def test_hidden_when_disabled(monkeypatch: pytest.MonkeyPatch, position: str) -> None:
    view = _setup(monkeypatch, enabled=False, position=position)
    plain = _plain(_build(view, 80))
    assert not any(ICON_TERMINAL in p or 'shell commands' in p for p in plain)


def test_badge_warns_on_high_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    cmds = (_cmd('busy', cpu=95.0),)
    spec = _build(_setup(monkeypatch, cmds=cmds), 80)
    row = next(r.content for r in spec.rows if ICON_TERMINAL in r.content)
    assert f'{CLR_WARN}95%' in row


def test_badge_not_warn_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _build(_setup(monkeypatch), 80)
    row = next(r.content for r in spec.rows if ICON_TERMINAL in r.content)
    assert CLR_WARN not in row


def test_list_warns_on_high_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    cmds = (_cmd('hog', rss_kb=2048 * 1024),)
    spec = _build(_setup(monkeypatch, cmds=cmds, style='list', position='below'), 80)
    row = next(r.content for r in spec.rows if strip_ansi(r.content).lstrip().startswith('bg'))
    assert f'{CLR_WARN}' in row and '2.0G' in strip_ansi(row)


def test_badge_omits_hidden_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _setup(monkeypatch, elapsed=ElapsedConfig(enabled=False),
                  cpu=CpuConfig(enabled=False), memory=MemoryConfig(enabled=False))
    badge = strip_ansi(_r.shell_commands_badge(view.shell_commands, view.cfg.shell_commands))
    assert badge == f'{ICON_TERMINAL} 3'


@pytest.mark.parametrize('position', ('right', 'below'))
@pytest.mark.parametrize('subs', (0, 2))
@pytest.mark.parametrize('width', (80, 100, 140))
def test_rendered_lines_have_equal_visible_width(
    monkeypatch: pytest.MonkeyPatch, width: int, subs: int, position: str,
) -> None:
    spec = _build(_setup(monkeypatch, subs=subs, position=position, max_items=2), width)
    widths = {_visible_width(line) for line in layout.render_layout(spec, _r)}
    assert widths == {width}


@pytest.mark.parametrize('width', WIDTHS)
def test_list_rows_share_left_padding_with_other_rows(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    cmds = DEFAULT_CMDS + (_cmd('extra'),)
    spec = _build(_setup(monkeypatch, cmds=cmds, style='list', position='below', max_items=2), width)
    lines = [strip_ansi(line) for line in layout.render_layout(spec, _r)]
    assert {_visible_width(line) for line in lines} == {width}

    def first_col(line: str) -> int:
        body = line[1:]
        return len(body) - len(body.lstrip(' ')) + 1

    sub = next(line for line in lines if 'agent0' in line)
    header = next(line for line in lines if 'shell commands (4)' in line)
    row = next(line for line in lines if line[1:].lstrip().startswith('bg'))
    more = next(line for line in lines if '+2 more' in line)
    other_col = first_col(sub)
    assert first_col(header) == other_col
    assert first_col(row) == other_col
    assert more.index('+2 more') == row.index('uv run pytest')


@pytest.mark.parametrize('inner', (40, 76, 136))
def test_list_lines_all_match_inner_width(inner: int) -> None:
    cfg = ShellCommandsConfig(max_items=2)
    sc = RunningShellCommands(commands=DEFAULT_CMDS)
    lines = _r.shell_commands_list(sc, cfg, inner)
    assert any('+1 more' in strip_ansi(line) for line in lines)
    assert {_visible_width(line) for line in lines} == {inner}


@pytest.mark.parametrize('width', WIDTHS)
def test_badge_style_aligns_every_row_and_changes_only_first_subagent_row(
    monkeypatch: pytest.MonkeyPatch, width: int,
) -> None:
    with_badge = layout.render_layout(_build(_setup(monkeypatch, subs=3), width), _r)
    baseline   = layout.render_layout(_build(_setup(monkeypatch, subs=3, enabled=False), width), _r)

    assert {_visible_width(line) for line in with_badge} == {width}
    assert len(with_badge) == len(baseline)

    changed = [i for i, (a, b) in enumerate(zip(with_badge, baseline)) if a != b]
    assert len(changed) == 1
    assert 'agent0' in strip_ansi(with_badge[changed[0]])
    assert ICON_TERMINAL in strip_ansi(with_badge[changed[0]])
    assert all('agent' in strip_ansi(with_badge[i]) for i in (changed[0] + 1, changed[0] + 2))


SIDE = {'style': 'list', 'position': 'right'}
SIDE_WIDTHS = (140, 200)


def _side_lines(spec: layout.LayoutSpec) -> list[str]:
    return [strip_ansi(line) for line in layout.render_layout(spec, _r)]


def _side_block(lines: list[str]) -> list[str]:
    'Rows between the header row (first side row) and the last row holding a second inner divider.'
    inner = [i for i, line in enumerate(lines) if line.count('│') == 3]
    return lines[inner[0]:inner[-1] + 1]


@pytest.mark.parametrize('width', SIDE_WIDTHS)
def test_side_rows_share_width_and_divider_column(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    lines = _side_lines(_build(_setup(monkeypatch, **SIDE), width))
    assert {_visible_width(line) for line in lines} == {width}
    block = _side_block(lines)
    assert len(block) == 4
    assert len({line.index('│', 2) for line in block}) == 1
    assert 'agent0' in block[0] and 'shell commands (3)' in block[0]


@pytest.mark.parametrize('width', SIDE_WIDTHS)
def test_side_elbows_sit_on_divider_column(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    lines = _side_lines(_build(_setup(monkeypatch, **SIDE), width))
    first = next(i for i, line in enumerate(lines) if line.count('│') == 3)
    last = max(i for i, line in enumerate(lines) if line.count('│') == 3)
    col = lines[first].index('│', 2)
    assert lines[first - 1][col] == '┬'
    assert lines[last + 1][col] == '┴'


@pytest.mark.parametrize('width', SIDE_WIDTHS)
def test_side_numbers_follow_command_column(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    lines = _side_lines(_build(_setup(monkeypatch, **SIDE), width))
    row = next(line for line in lines if 'uv run pytest -q' in line)
    tail = row[row.index('uv run pytest -q') + len('uv run pytest -q'):].rstrip(' │')
    assert tail.strip() == '5%  20M   1:12'
    longest = max(len(c.command) for c in DEFAULT_CMDS)
    after_cmd = row.index('uv run pytest -q') + longest
    assert row[after_cmd:after_cmd + 2] == '  '
    assert row[after_cmd + 2:].lstrip(' ')[:2] == '5%'


@pytest.mark.parametrize('subs, cmds', [(1, 4), (4, 2)])
def test_side_pads_shorter_section(monkeypatch: pytest.MonkeyPatch, subs: int, cmds: int) -> None:
    commands = tuple(_cmd(f'job{i}') for i in range(cmds))
    spec = _build(_setup(monkeypatch, subs=subs, cmds=commands, **SIDE), 140)
    lines = _side_lines(spec)
    assert {_visible_width(line) for line in lines} == {140}
    inner = [i for i, line in enumerate(lines) if line.count('│') == 3]
    block = lines[inner[0]:inner[-1] + 1]
    assert len(block) == max(subs, cmds + 1)
    assert len({line.index('│', 2) for line in block}) == 1


def test_side_command_numbers_hidden_groups_keep_alignment(monkeypatch: pytest.MonkeyPatch) -> None:
    cmds = tuple(_cmd(f'c{i}') for i in range(4))
    spec = _build(_setup(monkeypatch, cmds=cmds, max_items=2, **SIDE), 140)
    lines = _side_lines(spec)
    more = next(line for line in lines if '+2 more' in line)
    cmd = next(line for line in lines if ' c0 ' in line)
    assert more.index('+2 more') == cmd.index('c0')


def test_side_falls_back_to_list_below_when_narrow(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _build(_setup(monkeypatch, **SIDE), 80)
    lines = _side_lines(spec)
    assert {_visible_width(line) for line in lines} == {80}
    assert not any('agent0' in line and 'shell commands' in line for line in lines)
    assert any('shell commands (3)' in line for line in lines)
    assert any(line[1:].lstrip().startswith('bg') for line in lines)


@pytest.mark.parametrize('width', (80, 140))
def test_side_without_subagents_renders_list_below(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    lines = _side_lines(_build(_setup(monkeypatch, subs=0, **SIDE), width))
    assert {_visible_width(line) for line in lines} == {width}
    header = next(line for line in lines if 'shell commands (3)' in line)
    assert header.count('│') == (3 if width >= 120 else 2)


@pytest.mark.parametrize('width', WIDTHS)
def test_badge_below_is_own_row_under_subagents(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    lines = _side_lines(_build(_setup(monkeypatch, position='below'), width))
    assert {_visible_width(line) for line in lines} == {width}
    badge_rows = [i for i, line in enumerate(lines) if ICON_TERMINAL in line]
    assert len(badge_rows) == 1
    assert 'agent' not in lines[badge_rows[0]]
    assert 'agent1' in lines[badge_rows[0] - 1]
    assert '14:00' in lines[badge_rows[0]]


@pytest.mark.parametrize('width', (80, 200))
def test_list_below_numbers_follow_command_column(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    cmds = (_cmd('sleep 240', cpu=0.0), _cmd('python3 -c "import time"', cpu=99.0))
    spec = _build(_setup(monkeypatch, cmds=cmds, style='list', position='below', subs=0), width)
    lines = [strip_ansi(line) for line in layout.render_layout(spec, _r)]
    assert {_visible_width(line) for line in lines} == {width}
    rows = [line for line in lines if line[1:].lstrip().startswith('bg')]
    assert len(rows) == 2
    cmd_w = max(len('sleep 240'), len('python3 -c "import time"'))
    for row in rows:
        assert row.index('%') == row.index('bg') + 4 + cmd_w + 2 + 2
    if width == 200:
        assert all(len(row.rstrip('│ ')) < 60 for row in rows)


def test_list_below_truncates_long_commands_at_narrow_width(monkeypatch: pytest.MonkeyPatch) -> None:
    cmds = (_cmd('x' * 120), _cmd('short'))
    spec = _build(_setup(monkeypatch, cmds=cmds, style='list', position='below', subs=0), 80)
    lines = [strip_ansi(line) for line in layout.render_layout(spec, _r)]
    assert {_visible_width(line) for line in lines} == {80}
    assert any('…' in line for line in lines)


LABEL_TITLE = 'ˢʰᵉˡˡ ᶜᵒᵐᵐᵃⁿᵈˢ ⁽³⁾'
LABEL_WIDTHS = (140, 200)
LABEL_LAYOUTS = (('right', 2), ('below', 2), ('below', 0))


def _label_lines(monkeypatch: pytest.MonkeyPatch, width: int, position: str, subs: int, **kw) -> list[str]:
    view = _setup(monkeypatch, subs=subs, style='list', position=position, **kw)
    return [strip_ansi(line) for line in layout.render_layout(_build(view, width), _r)]


@pytest.mark.parametrize('position,subs', LABEL_LAYOUTS)
@pytest.mark.parametrize('width', LABEL_WIDTHS)
def test_labels_replace_header_row(monkeypatch: pytest.MonkeyPatch, width: int, position: str, subs: int) -> None:
    lines = _label_lines(monkeypatch, width, position, subs, labels=True)
    assert {_visible_width(line) for line in lines} == {width}
    assert not any('shell commands (3)' in line for line in lines)
    sep = next(line for line in lines if LABEL_TITLE in line)
    assert sep.startswith('├')


@pytest.mark.parametrize('position,subs', LABEL_LAYOUTS)
@pytest.mark.parametrize('width', LABEL_WIDTHS)
def test_header_row_kept_when_labels_off(monkeypatch: pytest.MonkeyPatch, width: int, position: str, subs: int) -> None:
    lines = _label_lines(monkeypatch, width, position, subs)
    assert any('shell commands (3)' in line for line in lines)
    assert not any(LABEL_TITLE in line for line in lines)


@pytest.mark.parametrize('position,subs', LABEL_LAYOUTS)
@pytest.mark.parametrize('width', LABEL_WIDTHS)
def test_column_labels_sit_over_their_columns(monkeypatch: pytest.MonkeyPatch, width: int, position: str, subs: int) -> None:
    lines = _label_lines(monkeypatch, width, position, subs, labels=True)
    sep = next(line for line in lines if LABEL_TITLE in line)
    row = next(line for line in lines if 'bg  uv run pytest -q' in line)
    cpu_end = row.index('%') + 1
    mem_end = row.index('M') + 1
    time_end = row.index('1:12') + 4
    assert sep.index('ᶜᵖᵘ') + 3 == cpu_end
    if subs:  # without subagents the tokens-row elbows can land on the mem label and drop it
        assert sep.index('ᵐᵉᵐ') + 3 == mem_end
    assert sep.index('ᵗⁱᵐᵉ') + 4 == time_end


@pytest.mark.parametrize('position,subs', LABEL_LAYOUTS)
def test_disabled_column_has_no_label(monkeypatch: pytest.MonkeyPatch, position: str, subs: int) -> None:
    lines = _label_lines(monkeypatch, 200, position, subs, labels=True, cpu=CpuConfig(enabled=False))
    sep = next(line for line in lines if LABEL_TITLE in line)
    assert 'ᶜᵖᵘ' not in sep
    if subs:  # without subagents tokens-row elbows can drop a label
        assert 'ᵐᵉᵐ' in sep and 'ᵗⁱᵐᵉ' in sep


@pytest.mark.parametrize('seconds', (7, 72, 599, 600, 840, 3599, 3600, 3725))
def test_shell_elapsed_matches_shared_duration_format(seconds: int) -> None:
    from yas.render.tasks_view import fmt_duration
    cfg = ShellCommandsConfig(cpu=CpuConfig(enabled=False), memory=MemoryConfig(enabled=False))
    sc = RunningShellCommands(commands=(_cmd('a', elapsed=seconds), _cmd('b', elapsed=1)))
    side = [strip_ansi(line) for line in _r.shell_commands_side(sc, cfg)]
    assert side[1].rstrip().endswith(fmt_duration(seconds))
    assert len({len(line) for line in side}) == 1
    badge = strip_ansi(_r.shell_commands_badge(sc, cfg))
    assert badge.endswith(fmt_duration(seconds)) or fmt_duration(seconds) in badge


LONG_ACTIVITY = 'cd /tmp/work && ' + 'echo long-activity-line ' * 4
NUMBERS = ' 5%  20M  1:12'


def _side_view(monkeypatch: pytest.MonkeyPatch, cmds, **kw) -> SessionView:
    return _setup(monkeypatch, cmds=cmds, labels=True, style='list', position='right', activity=LONG_ACTIVITY, **kw)


def _side_cells(lines: list[str]) -> list[tuple[str, str]]:
    'Left and right cell of every row that has a divider (outer borders excluded).'
    return [(parts[1], parts[2]) for parts in (line.split('│') for line in lines) if len(parts) == 4]


def _cmd_cell(lines: list[str]) -> tuple[str, str]:
    'The first command row: (right cell, displayed command text).'
    right = next(r for _, r in _side_cells(lines) if r.strip().startswith('bg'))
    return right, right.strip().removeprefix('bg  ').removesuffix(NUMBERS).rstrip(' ')


def test_side_divider_sits_after_subagent_natural_width(monkeypatch: pytest.MonkeyPatch) -> None:
    cmds = (_cmd('make ' + 'x' * 400),)
    at_300 = _side_lines(_build(_side_view(monkeypatch, cmds), 300))
    at_340 = _side_lines(_build(_side_view(monkeypatch, cmds), 340))
    assert {_visible_width(line) for line in at_300} == {300}
    assert _divider_col(at_300) == _divider_col(at_340)
    gaps = [len(left) - len(left.rstrip(' ')) for left, _ in _side_cells(at_300)]
    assert min(gaps) == 1  # the longest subagent row ends one pad space before the divider
    assert _divider_col(at_300) < 300 - 40


def _divider_col(lines: list[str]) -> int:
    return next(line for line in lines if line.count('│') == 3).index('│', 2)


def test_side_command_shown_in_full_and_side_is_natural_width(monkeypatch: pytest.MonkeyPatch) -> None:
    cmd = 'make ' + 'x' * 70
    lines = _side_lines(_build(_side_view(monkeypatch, (_cmd(cmd),)), 300))
    right, shown = _cmd_cell(lines)
    assert shown == cmd
    assert right == f' bg  {cmd}  {NUMBERS} '
    assert {_visible_width(line) for line in lines} == {300}


def test_side_short_commands_leave_the_rest_to_subagents(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = _side_lines(_build(_side_view(monkeypatch, (_cmd('make test'),)), 300))
    right, shown = _cmd_cell(lines)
    assert right == f' bg  make test  {NUMBERS} '
    assert _divider_col(lines) == 300 - 2 - len(right)


def test_side_command_truncated_to_exactly_remaining_width(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = _side_lines(_build(_side_view(monkeypatch, (_cmd('make ' + 'x' * 400),)), 300))
    right, shown = _cmd_cell(lines)
    assert shown.endswith('…') and len(shown) > 40
    assert len(right) == 1 + 4 + len(shown) + 2 + len(NUMBERS) + 1
    assert _divider_col(lines) == 300 - 2 - len(right)


def test_side_squeezed_keeps_command_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = _side_lines(_build(_side_view(monkeypatch, (_cmd('make ' + 'x' * 400),), max_command_width=40), 140))
    _, shown = _cmd_cell(lines)
    assert len(shown) == 40 and shown.endswith('…')
    assert {_visible_width(line) for line in lines} == {140}


def test_leading_cd_hidden_in_side_command(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = _side_lines(_build(_side_view(monkeypatch, (_cmd('cd /a/b && make test'),)), 300))
    assert _cmd_cell(lines)[1] == 'make test'


@pytest.mark.parametrize('position', ('right', 'below'))
def test_number_columns_have_equal_gaps_and_right_aligned_labels(monkeypatch: pytest.MonkeyPatch, position: str) -> None:
    cmds = (
        _cmd('sleep 240 # pad to clear the title', cpu=0.0, rss_kb=27 * 1024, elapsed=282),
        _cmd('make x', cpu=100.0, rss_kb=2048 * 1024, elapsed=3700),
    )
    view = _setup(monkeypatch, cmds=cmds, labels=True, style='list', position=position)
    lines = _side_lines(_build(view, 200))
    sep = next(line for line in lines if 'ˢʰᵉˡˡ ᶜᵒᵐᵐᵃⁿᵈˢ ⁽²⁾' in line)
    pattern = re.compile(r'(\S+) +(\S+) +(\S+)$')
    tokens, ends = [], set()
    for text in ('bg  sleep 240', 'bg  make x'):
        row = next(line for line in lines if text in line)
        cell = row.split('\u2502')[-2 if position == 'right' else -3].rstrip(' ')
        m = pattern.search(cell)
        base = row.rindex(cell)
        tokens.append(m.groups())
        ends.add((base + m.end(1), base + m.end(2), base + m.end(3), row.index('bg') + 4 + len('sleep 240 # pad to clear the title')))
    assert len(ends) == 1
    cpu_end, mem_end, time_end, cmd_end = ends.pop()
    cpu_w, mem_w, time_w = (max([len(label)] + [len(t[k]) for t in tokens]) for k, label in enumerate(('cpu', 'mem', 'time')))
    assert cpu_end - cpu_w - cmd_end == 2
    assert mem_end - mem_w - cpu_end == 2
    assert time_end - time_w - mem_end == 2
    assert sep.index('ᶜᵖᵘ') + 3 == cpu_end
    assert sep.index('ᵐᵉᵐ') + 3 == mem_end
    assert sep.index('ᵗⁱᵐᵉ') + 4 == time_end


CLOSED_CMDS = (_cmd('make test', cpu=99.0), _cmd('sleep 240', cpu=0.0))


def _closed_lines(monkeypatch: pytest.MonkeyPatch, width: int, position: str, labels: bool) -> list[str]:
    view = _setup(monkeypatch, cmds=CLOSED_CMDS, subs=0, labels=labels, style='list', position=position)
    return _side_lines(_build(view, width))


@pytest.mark.parametrize('labels', (True, False))
@pytest.mark.parametrize('position', ('below', 'right'))
@pytest.mark.parametrize('width', (140, 200))
def test_list_without_subagents_is_closed_by_divider_with_elbows(
    monkeypatch: pytest.MonkeyPatch, width: int, position: str, labels: bool,
) -> None:
    lines = _closed_lines(monkeypatch, width, position, labels)
    assert {_visible_width(line) for line in lines} == {width}
    rows = [i for i, line in enumerate(lines) if line.count('│') == 3]
    assert len(rows) == (2 if labels else 3)
    col = lines[rows[0]].index('│', 2)
    assert {lines[i].index('│', 2) for i in rows} == {col}
    assert lines[rows[0] - 1][col] == '┬'
    assert lines[rows[-1] + 1][col] == '┴'
    assert lines[rows[-1]][2:col].rstrip().endswith('1:12')
    assert lines[rows[0]][col - 1] == ' '
    assert lines[rows[0]][col + 1:].strip(' │') == ''


@pytest.mark.parametrize('position', ('below', 'right'))
def test_closed_list_header_row_sits_left_of_divider_when_labels_off(monkeypatch: pytest.MonkeyPatch, position: str) -> None:
    lines = _closed_lines(monkeypatch, 140, position, False)
    header = next(line for line in lines if 'shell commands (2)' in line)
    assert header.index('│', 2) > header.index('shell commands (2)')
    assert header.count('│') == 3


def test_closed_list_label_row_keeps_its_elbow_and_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = _closed_lines(monkeypatch, 200, 'below', True)
    sep = next(line for line in lines if 'ˢʰᵉˡˡ ᶜᵒᵐᵐᵃⁿᵈˢ ⁽²⁾' in line)
    row = next(line for line in lines if 'bg  make test' in line)
    assert sep[row.index('│', 2)] == '┬'
    assert 'ᵗⁱᵐᵉ' in sep  # other labels can be dropped under the tokens-row elbows above


def _one_cmd_lines(monkeypatch: pytest.MonkeyPatch, length: int, width: int, position: str = 'below') -> list[str]:
    view = _setup(monkeypatch, cmds=(_cmd('x' * length),), subs=0, labels=True, style='list', position=position)
    return _side_lines(_build(view, width))


def _command_row(lines: list[str]) -> str:
    return next(line for line in lines if 'bg  x' in line)


# Block width is 21 + command length; the divider needs 60 empty columns right of it,
# so at 140 columns a command of 53 columns is the longest that keeps the divider.
@pytest.mark.parametrize('position', ('below', 'right'))
def test_closing_divider_present_when_leftover_space_is_at_least_60(monkeypatch: pytest.MonkeyPatch, position: str) -> None:
    row = _command_row(_one_cmd_lines(monkeypatch, 53, 140, position))
    assert row.count('│') == 3
    assert len(row.split('│')[2]) - 1 == 60  # blank columns right of the divider (plus the border pad)


@pytest.mark.parametrize('position', ('below', 'right'))
def test_closing_divider_absent_when_leftover_space_is_below_60(monkeypatch: pytest.MonkeyPatch, position: str) -> None:
    lines = _one_cmd_lines(monkeypatch, 54, 140, position)
    assert {_visible_width(line) for line in lines} == {140}
    assert not any(line.count('│') == 3 for line in lines)
    assert 'x' * 54 in _command_row(lines)  # still sized by the grown cap, not cut to max_command_width


def test_no_subagent_list_command_grows_past_max_command_width(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _command_row(_one_cmd_lines(monkeypatch, 70, 300))
    assert 'x' * 70 in row and '…' not in row


def test_no_subagent_list_command_capped_at_twice_max_command_width(monkeypatch: pytest.MonkeyPatch) -> None:
    for width in (140, 300):
        row = _command_row(_one_cmd_lines(monkeypatch, 200, width))
        shown = row.split('bg  ')[1].split('…')[0]
        assert len(shown) == 79 and row.count('…') == 1


def test_no_subagent_list_open_when_box_is_narrow(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = _one_cmd_lines(monkeypatch, 20, 80)
    assert {_visible_width(line) for line in lines} == {80}
    assert not any(line.count('│') == 3 for line in lines)


def _sub_closed_lines(monkeypatch: pytest.MonkeyPatch, width: int, cmd_len: int | None = None, labels: bool = True) -> list[str]:
    cmds = CLOSED_CMDS if cmd_len is None else (_cmd('x' * cmd_len),)
    view = _setup(monkeypatch, cmds=cmds, subs=1, labels=labels, style='list', position='below')
    return _side_lines(_build(view, width))


def test_list_below_with_subagents_is_closed_by_divider_with_elbows(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = _sub_closed_lines(monkeypatch, 200)
    row = next(line for line in lines if 'bg  make test' in line)
    col = row.index('│', 2)
    assert row.count('│') == 3
    sep = next(i for i, line in enumerate(lines) if 'ˢʰᵉˡˡ ᶜᵒᵐᵐᵃⁿᵈˢ ⁽²⁾' in line)
    last = max(i for i, line in enumerate(lines) if line.count('│') == 3)
    assert lines[sep][col] == '┬'
    assert lines[last + 1][col] == '┴'


def test_list_below_with_subagents_rows_share_visible_width(monkeypatch: pytest.MonkeyPatch) -> None:
    for labels in (True, False):
        lines = _sub_closed_lines(monkeypatch, 200, labels=labels)
        assert {_visible_width(line) for line in lines} == {200}


def test_list_below_with_subagents_keeps_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    sep = next(line for line in _sub_closed_lines(monkeypatch, 200) if 'ˢʰᵉˡˡ' in line)
    assert 'ᵐᵉᵐ' in sep and 'ᵗⁱᵐᵉ' in sep  # cpu may be dropped under the tokens-row elbows above


def test_list_below_with_subagents_header_inside_block_when_labels_off(monkeypatch: pytest.MonkeyPatch) -> None:
    header = next(line for line in _sub_closed_lines(monkeypatch, 200, labels=False) if 'shell commands (2)' in line)
    assert header.count('│') == 3 and header.index('│', 2) > header.index('shell commands (2)')


def test_list_below_with_subagents_open_when_fewer_than_60_columns_remain(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = _sub_closed_lines(monkeypatch, 140, cmd_len=54)
    assert {_visible_width(line) for line in lines} == {140}
    assert not any(line.count('│') == 3 for line in lines)
    closed = _sub_closed_lines(monkeypatch, 140, cmd_len=53)
    assert any(line.count('│') == 3 for line in closed)
