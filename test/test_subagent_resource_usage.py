"""Per-subagent resource columns: ownership matching, shell section split, row display."""
import json
import time
from pathlib import Path

import pytest

import yas.info.subagents as subagents_mod
import yas.layout as layout
from helper import iso_ts, strip_ansi
from yas.config import AgentsConfig, Config, ResourceUsageConfig, ShellCommandsConfig
from yas.constants import CLR_WARN, ICON_TERMINAL, SHELL_COL_GAP
from yas.info import SessionView
from yas.info.bash_inflight import fold_line, inflight
from yas.info.parsecache import TranscriptCache
from yas.info.shell_commands import AgentUsage, split_by_owner
from yas.render.text import _visible_width
from yas.renderer import Renderer
from yas.tokens import TickRecord, TokenLog

NOW = 100_000.0


def _use(tid: str, command: str, ts: float, *, bg: bool = False) -> str:
    return json.dumps({
        'type': 'assistant', 'timestamp': iso_ts(ts),
        'message': {'id': f'm-{tid}', 'content': [{
            'type': 'tool_use', 'id': tid, 'name': 'Bash',
            'input': {'command': command, 'run_in_background': bg},
        }]},
    })


def _result(tid: str, ts: float) -> str:
    return json.dumps({
        'type': 'user', 'timestamp': iso_ts(ts),
        'message': {'content': [{'type': 'tool_result', 'tool_use_id': tid, 'content': 'ok'}]},
    })


def _flight(*lines: str) -> tuple[tuple[str, float], ...]:
    state: dict = {}
    for ln in lines:
        fold_line(state, ln)
    return inflight(state)


# ---- in-flight collection -------------------------------------------------

def test_foreground_call_without_result_is_in_flight() -> None:
    assert _flight(_use('t1', 'make   test', 50))[0][0] == 'make test'


def test_background_call_stays_in_flight_after_its_result() -> None:
    calls = _flight(_use('t1', 'tail -f x', 50, bg=True), _result('t1', 51))
    assert [c for c, _ in calls] == ['tail -f x']


def test_finished_foreground_call_is_not_in_flight() -> None:
    assert _flight(_use('t1', 'make test', 50), _result('t1', 51)) == ()


def test_in_flight_keeps_full_command_text() -> None:
    long = 'echo ' + 'x' * 300
    assert _flight(_use('t1', long, 50))[0][0] == long


def test_in_flight_is_collected_by_the_subagent_scan(tmp_home: Path) -> None:
    now = time.time()
    sdir = tmp_home / '.claude' / 'projects' / '-home-u-p' / 'sess' / 'subagents'
    sdir.mkdir(parents=True)
    (sdir / 'agent-a1.meta.json').write_text(json.dumps({'agentType': 'Explore', 'description': 'd'}))
    lines = [_use('t1', 'sleep 30', now - 20), _use('t2', 'make done', now - 15), _result('t2', now - 10)]
    (sdir / 'agent-a1.jsonl').write_text('\n'.join(lines) + '\n')
    subs = subagents_mod.RunningSubagents.from_session('sess', '/home/u/p', now=now).subagents
    assert [c for c, _ in subs[0].bash_inflight] == ['sleep 30']


# ---- ownership matching ---------------------------------------------------

def _split(commands, owners, main=(), now=NOW):
    return split_by_owner(tuple(commands), owners, lambda: tuple(main), now)


def test_command_matching_an_in_flight_call_is_owned(make_shell_command) -> None:
    mine, theirs = _split([make_shell_command('sleep 30', elapsed=20)], {'a1': (('sleep 30', NOW - 21),)})
    assert mine == ()
    assert [c.command for c in theirs['a1']] == ['sleep 30']


def test_command_without_a_matching_call_stays_with_main(make_shell_command) -> None:
    mine, theirs = _split([make_shell_command('sleep 30')], {'a1': (('sleep 99', NOW - 20),)})
    assert len(mine) == 1
    assert theirs == {}


def test_identical_command_resolves_to_closest_start_time(make_shell_command) -> None:
    owners = {'a1': (('make', NOW - 500),), 'a2': (('make', NOW - 61),)}
    _, theirs = _split([make_shell_command('make', elapsed=60)], owners)
    assert list(theirs) == ['a2']


def test_subagent_beats_main_when_its_call_started_closer(make_shell_command) -> None:
    mine, theirs = _split([make_shell_command('make', elapsed=60)], {'a1': (('make', NOW - 61),)}, main=[('make', NOW - 900)])
    assert mine == ()
    assert list(theirs) == ['a1']


def test_main_keeps_command_when_its_call_started_closer(make_shell_command) -> None:
    mine, theirs = _split([make_shell_command('make', elapsed=60)], {'a1': (('make', NOW - 900),)}, main=[('make', NOW - 61)])
    assert len(mine) == 1
    assert theirs == {}


def test_ambiguous_owners_leave_command_in_shell_section(make_shell_command) -> None:
    owners = {'a1': (('make', NOW - 61),), 'a2': (('make', NOW - 61.2),)}
    mine, theirs = _split([make_shell_command('make', elapsed=60)], owners)
    assert len(mine) == 1
    assert theirs == {}


def test_owner_calls_more_than_a_second_apart_resolve_to_the_closest(make_shell_command) -> None:
    # The process starts between the two calls, so distance-from-start made the
    # gap look like 0.5 s even though the calls are 2.5 s apart. Compare the
    # owners' call timestamps directly: a2 is closest and has no tie.
    owners = {'a1': (('make', NOW - 102.5),), 'a2': (('make', NOW - 100),)}
    _, theirs = _split([make_shell_command('make', elapsed=101)], owners)
    assert list(theirs) == ['a2']


def test_owner_calls_within_a_second_leave_command_with_main(make_shell_command) -> None:
    owners = {'a1': (('make', NOW - 101),), 'a2': (('make', NOW - 100.5),)}
    mine, theirs = _split([make_shell_command('make', elapsed=101)], owners)
    assert len(mine) == 1
    assert theirs == {}


def test_one_call_is_claimed_by_one_process(make_shell_command) -> None:
    cmds = [make_shell_command('make', elapsed=60), make_shell_command('make', elapsed=10)]
    mine, theirs = _split(cmds, {'a1': (('make', NOW - 61),)})
    assert [c.elapsed_s for c in mine] == [10]
    assert [c.elapsed_s for c in theirs['a1']] == [60]


# ---- view split -----------------------------------------------------------

@pytest.fixture
def make_sub(make_subagent):
    def make(agent_id: str, calls=(), activity: str = 'pytest', status: str = 'running') -> subagents_mod.RunningSubagent:
        now = time.time()
        return make_subagent(
            agent_id, now=now, agent_id=agent_id, activity=activity, status=status,
            start_ago=10, mtime_ago=5, bash_inflight=tuple(calls),
        )
    return make


@pytest.fixture
def build_view(make_view):
    def make(
        subs, cmds, *, labels: bool = False,
        agents: AgentsConfig | None = None, shell: ShellCommandsConfig | None = None,
    ) -> SessionView:
        cfg = Config(
            labels=labels,
            shell_commands=shell or ShellCommandsConfig(style='list', position='below'),
            agents=agents or AgentsConfig(),
        )
        return make_view(cfg=cfg, subs=subs, commands=tuple(cmds), now=NOW)
    return make


@pytest.fixture
def owned_view(build_view, make_sub, make_shell_command):
    def make(**kw) -> SessionView:
        t = NOW - 21
        subs = [make_sub('a1', [('sleep 30', t)]), make_sub('a2')]
        cmds = [
            make_shell_command('sleep 30', elapsed=20, cpu=12.0, rss_kb=100 * 1024),
            make_shell_command('make demo', elapsed=5),
        ]
        return build_view(subs, cmds, **kw)
    return make


def test_shell_section_excludes_owned_processes(owned_view) -> None:
    view = owned_view()
    assert [c.command for c in view.shell_commands.commands] == ['make demo']
    # a1 owns the live process; a2 has no process and is thinking.
    assert set(view.subagent_usage) == {'a1', 'a2'}
    assert view.subagent_usage['a2'].thinking is True


def test_usage_sums_cpu_and_memory_and_takes_longest_elapsed(build_view, make_sub, make_shell_command) -> None:
    subs = [make_sub('a1', [('x', NOW - 100), ('y', NOW - 31)])]
    cmds = [make_shell_command('x', elapsed=99, cpu=10.0, rss_kb=1024), make_shell_command('y', elapsed=30, cpu=2.5, rss_kb=2048)]
    usage = build_view(subs, cmds).subagent_usage['a1']
    assert (usage.cpu_percent, usage.rss_kb, usage.elapsed_s) == (12.5, 3072, 99)


def test_shell_section_hidden_when_all_processes_are_owned(build_view, make_sub, make_shell_command) -> None:
    view = build_view([make_sub('a1', [('sleep 30', NOW - 21)])], [make_shell_command('sleep 30', elapsed=20)])
    assert not view.shell_commands
    assert view.shell_commands.count == 0


def test_disabled_resource_usage_keeps_processes_in_shell_section(owned_view) -> None:
    agents = AgentsConfig(resource_usage=ResourceUsageConfig(enabled=False))
    view = owned_view(agents=agents)
    assert view.shell_commands.count == 2
    assert view.subagent_usage == {}


def test_disabled_resource_usage_keeps_the_running_bash_call_on_the_agent_row(renderer, owned_view) -> None:
    agents = AgentsConfig(resource_usage=ResourceUsageConfig(enabled=False))
    rows = _agent_rows(_build(owned_view(agents=agents), 200, renderer))
    own = next(r for r in rows if 'a1' in r)
    assert 'Bash[' in own
    assert '(thinking)' not in own


def test_disabled_shell_commands_keeps_the_running_bash_call_on_the_agent_row(renderer, owned_view) -> None:
    shell = ShellCommandsConfig(enabled=False, style='list', position='below')
    rows = _agent_rows(_build(owned_view(shell=shell), 200, renderer))
    own = next(r for r in rows if 'a1' in r)
    assert 'Bash[' in own
    assert '(thinking)' not in own


def test_finished_agent_with_a_stale_background_call_retires(make_subagent) -> None:
    # A background Bash call stays in `bash_inflight` forever, so it must not
    # pin a Done agent's row after its normal retirement horizon.
    sub = make_subagent(
        'worker', now=NOW, end_ts=NOW - 1000, mtime_ago=1000,
        bash_inflight=(('sleep 99999', NOW - 2000),),
    )
    cohort = subagents_mod.RunningSubagents(subagents=[sub])
    assert cohort.visible(NOW, None) == []


def test_finished_subagent_does_not_own_processes(build_view, make_sub, make_shell_command) -> None:
    view = build_view([make_sub('a1', [('sleep 30', NOW - 21)], status='completed')], [make_shell_command('sleep 30', elapsed=20)])
    assert view.shell_commands.count == 1


# ---- row display ----------------------------------------------------------

def _build(view: SessionView, width: int, renderer: Renderer) -> layout.LayoutSpec:
    tick = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    if width >= 120:
        return layout.build_wide(view, tick, width, renderer)
    return layout.build_narrow(view, width, renderer)


def _contents(spec: layout.LayoutSpec) -> list[str]:
    return [row.content for row in spec.rows if row.kind == 'content']


def _agent_rows(spec: layout.LayoutSpec) -> list[str]:
    return [strip_ansi(c) for c in _contents(spec) if 'a1' in strip_ansi(c) or 'a2' in strip_ansi(c)]


def _block_widths(spec: layout.LayoutSpec) -> set[int]:
    'Visible widths of the subagent and shell rows (the other rows are sized elsewhere).'
    keep = ('a1', 'a2', 'shell commands', 'fg ', 'bg ')
    return {_visible_width(c) for c in _contents(spec) if any(k in strip_ansi(c) for k in keep)}


@pytest.mark.parametrize('width', (80, 140, 200))
def test_owning_row_shows_cpu_mem_elapsed_and_other_row_is_blank(width: int, renderer, owned_view) -> None:
    rows = _agent_rows(_build(owned_view(), width, renderer))
    own = next(r for r in rows if 'a1' in r)
    other = next(r for r in rows if 'a2' in r)
    # Resources sit left of the activity/log column.
    assert '12%  100M  0:20' in own
    assert '12%' not in other and '100M' not in other
    assert _visible_width(own) == _visible_width(other)


@pytest.mark.parametrize('width', (80, 140, 200))
def test_columns_align_across_rows(width: int, renderer, build_view, make_sub, make_shell_command) -> None:
    subs = [make_sub('a1', [('x', NOW - 100)]), make_sub('a2', [('y', NOW - 4000)])]
    cmds = [make_shell_command('x', elapsed=99, cpu=3.0, rss_kb=5 * 1024), make_shell_command('y', elapsed=3990, cpu=250.0, rss_kb=2048 * 1024)]
    rows = _agent_rows(_build(build_view(subs, cmds), width, renderer))
    assert len(rows) == 2
    assert len({len(r.rstrip()) for r in rows}) == 1
    assert '  3%    5M     1:39' in rows[0]
    assert '250%  2.0G  1:06:30' in rows[1]
    # Wide rows put the resource block left of the activity/log column; narrow
    # one-line rows keep it right-aligned at the row end.
    if width > 100:
        assert rows[0].index('3%') < rows[0].index('Bash[')
        assert rows[1].index('250%') < rows[1].index('Bash[')
    else:
        assert rows[0].index('Bash[') < rows[0].index('3%')
        assert rows[1].index('Bash[') < rows[1].index('250%')


@pytest.mark.parametrize('width', (80, 140, 200))
def test_all_content_rows_keep_the_same_visible_width(width: int, renderer, owned_view) -> None:
    spec = _build(owned_view(labels=True), width, renderer)
    assert len(_block_widths(spec)) == 1


def test_warn_colour_uses_shell_thresholds(renderer, owned_view) -> None:
    shell = ShellCommandsConfig(cpu=ShellCommandsConfig().cpu._replace(warn_percent=10.0))
    own = next(c for c in _contents(_build(owned_view(shell=shell), 140, renderer)) if 'a1' in strip_ansi(c))
    assert f'{CLR_WARN}12%' in own


def test_labels_are_painted_over_the_columns(renderer, owned_view) -> None:
    spec = _build(owned_view(labels=True), 200, renderer)
    sep = next(row for row in spec.rows if any(name == 'cpu' for name, _ in row.labels))
    cols = dict(sep.labels)
    assert {'cpu', 'mem', 'time', 'agent'} <= set(cols)
    data = next(strip_ansi(c) for c in _contents(spec) if 'a1' in strip_ansi(c))
    # a label is right-aligned over its column; its last char sits over the value's last char
    # (border column - 3 is the content offset)
    assert data[cols['time'] - 3 + len('time') - 1] == '0'
    assert data[cols['cpu'] - 3 + len('cpu') - 1] == '%'
    assert cols['cpu'] < cols['mem'] < cols['time'] < cols['log']


def test_disabled_columns_are_omitted_with_their_labels(renderer, owned_view) -> None:
    agents = AgentsConfig(resource_usage=ResourceUsageConfig(memory=False, elapsed=False))
    spec = _build(owned_view(labels=True, agents=agents), 200, renderer)
    names = set(next(dict(row.labels) for row in spec.rows if any(n == 'cpu' for n, _ in row.labels)))
    assert {'agent', 'cpu'} <= names
    assert not names & {'mem', 'time'}
    own = next(strip_ansi(c) for c in _contents(spec) if 'a1' in strip_ansi(c))
    assert '12%' in own
    assert '100M' not in own and '0:20' not in own


def test_command_mode_current_rewrites_subagent_activity(renderer, build_view, make_sub, make_shell_command) -> None:
    sub = make_sub('a1', [('gate.sh make test | tail -4', NOW - 21)])
    cmd = make_shell_command(
        'gate.sh make test | tail -4',
        elapsed=20,
        cpu=12.0,
        rss_kb=100 * 1024,
        display_command='cargo test --test all generator::',
    )
    shell = ShellCommandsConfig(
        style='list', position='below', command_mode='current',
    )
    row = next(r for r in _agent_rows(_build(build_view([sub], [cmd], shell=shell), 140, renderer)) if 'a1' in r)
    assert 'Bash[cargo test --test all generator::]' in row
    assert 'gate.sh make test' not in row
    assert '12%' in row and '100M' in row


def test_default_rows_prefer_the_live_child_even_with_command_mode_chain(
    renderer,
    build_view,
    make_sub,
    make_shell_command,
) -> None:
    chain = 'gate.sh make test | tail -4'
    sub = make_sub('a1', [(chain, NOW - 21)])
    cmd = make_shell_command(chain, elapsed=20, cpu=12.0, live_command='make test')
    shell = ShellCommandsConfig(style='list', position='below', command_mode='chain')
    row = next(r for r in _agent_rows(_build(build_view([sub], [cmd], shell=shell), 140, renderer)) if 'a1' in r)
    assert 'Bash[make test]' in row
    assert 'gate.sh make test' not in row
    assert '12%' in row


def test_non_bash_current_tool_call_wins_over_owned_background_bash(
    renderer,
    build_view,
    make_sub,
    make_shell_command,
) -> None:
    # The agent still owns a long-running background Bash process, but its
    # current activity is a Write call: show the Write, not the Bash command.
    sub = make_sub('a1', [('cargo build', NOW - 95)])
    sub.last_activity = ('tool_use', 'Write', {'file_path': '/repo/src/main.py'})
    cmd = make_shell_command('cargo build', elapsed=95, cpu=12.0, rss_kb=100 * 1024)
    row = next(r for r in _agent_rows(_build(build_view([sub], [cmd]), 200, renderer)) if 'a1' in r)
    assert 'Write[main.py]' in row
    assert 'Bash[' not in row
    # The owned process still drives the resource columns.
    assert '12%' in row and '100M' in row and '1:35' in row


def test_thinking_is_not_masked_by_an_owned_background_bash_process(
    renderer,
    build_view,
    make_sub,
    make_shell_command,
) -> None:
    sub = make_sub('a1', [('cargo build', NOW - 95)])
    sub.last_activity = ('thinking', '', {})
    sub.last_activity_ts = NOW - 27
    cmd = make_shell_command('cargo build', elapsed=95, cpu=12.0, rss_kb=100 * 1024)
    row = next(r for r in _agent_rows(_build(build_view([sub], [cmd]), 200, renderer)) if 'a1' in r)
    assert '(thinking)' in row
    assert 'Bash[' not in row
    assert '12%' in row and '100M' in row


def test_read_activity_is_not_treated_as_thinking(build_view, make_sub) -> None:
    sub = make_sub('a1')
    sub.last_activity = ('tool_use', 'Read', {'file_path': 'x.py'})
    view = build_view([sub], [])
    assert view.subagent_usage == {}


def test_waiting_parent_row_shows_waiting_and_zero_resources(renderer, build_view, make_sub) -> None:
    parent = make_sub('a1')
    parent.last_activity = ('text', 'dispatched the worker', {})
    child = make_sub('a2', [('sleep 30', NOW - 47)])
    child.parent_id = 'a1'
    child.first_timestamp = NOW - 47
    child.run_start_ts = NOW - 47
    row = next(r for r in _agent_rows(_build(build_view([parent, child], []), 140, renderer)) if 'a1' in r)
    assert '(waiting)' in row
    assert '0%' in row and '0M' in row
    assert '0:47' in row


def test_parent_running_a_command_is_not_marked_waiting(renderer, build_view, make_sub, make_shell_command) -> None:
    parent = make_sub('a1', [('sleep 30', NOW - 21)])
    child = make_sub('a2')
    child.parent_id = 'a1'
    child.first_timestamp = NOW - 47
    child.run_start_ts = NOW - 47
    view = build_view([parent, child], [make_shell_command('sleep 30', elapsed=20)])
    assert 'waiting' not in view.subagents.subagents[0].last_activity[0]
    row = next(r for r in _agent_rows(_build(view, 140, renderer)) if 'a1' in r)
    assert '(waiting)' not in row


def test_no_columns_reserved_without_an_owned_process(renderer, build_view, make_sub, make_shell_command) -> None:
    rows = _agent_rows(_build(build_view([make_sub('a1'), make_sub('a2')], [make_shell_command('make demo')]), 140, renderer))
    # With no live process the rows are processing/thinking: they get the
    # thinking activity and the zero-resource columns, not a stale Bash label.
    assert all('(thinking)' in r for r in rows)
    assert all('0%' in r and '0M' in r for r in rows)


def test_activity_column_truncates_to_make_room(renderer, build_view, make_sub, make_shell_command) -> None:
    long = 'x' * 120
    view = build_view([make_sub('a1', [('sleep 30', NOW - 21)], activity=long), make_sub('a2', activity=long)],
                 [make_shell_command('sleep 30', elapsed=20)])
    rows = _agent_rows(_build(view, 140, renderer))
    assert all('…' in r or 'x' * 120 not in r for r in rows)
    assert '0:20' in rows[0]
    assert rows[0].index('0:20') < rows[0].index('Bash[')


def test_regular_section_keeps_owned_columns_and_drops_the_shell_block(renderer, owned_view) -> None:
    shell = ShellCommandsConfig(style='list', position='right')
    view = owned_view(labels=True, shell=shell)
    spec = _build(view, 200, renderer)
    assert len(_block_widths(spec)) == 1
    plain = [strip_ansi(c) for c in _contents(spec)]
    assert any('a1' in p and '12%' in p for p in plain)
    assert not any('shell commands' in p for p in plain)


def test_columns_omitted_when_the_row_would_fall_below_its_minimum(renderer, owned_view) -> None:
    rows = _agent_rows(_build(owned_view(), 40, renderer))
    assert rows
    assert not any('12%' in r for r in rows)


def test_plan_gap_matches_shell_section(renderer) -> None:
    plan = renderer.agent_usage_plan(
        {'a1': AgentUsage(cpu_percent=12.0, rss_kb=100 * 1024, elapsed_s=20)},
        ShellCommandsConfig(), ResourceUsageConfig(), labelled=False,
    )
    assert plan is not None
    assert plan.width == SHELL_COL_GAP + _visible_width(strip_ansi(plan.cells['a1']))
    assert strip_ansi(plan.cells['a1']) == '12%  100M  0:20'


@pytest.mark.parametrize('width', (80, 140, 200))
def test_badge_style_keeps_columns_and_draws_no_badge(width: int, renderer, owned_view) -> None:
    shell = ShellCommandsConfig(style='badge', position='right')
    spec = _build(owned_view(shell=shell), width, renderer)
    own = next(strip_ansi(c) for c in _contents(spec) if 'a1' in strip_ansi(c))
    assert '12%' in own
    assert not any(ICON_TERMINAL in strip_ansi(c) for c in _contents(spec))
    assert len(_block_widths(spec)) == 1


def test_main_inflight_reads_the_main_transcript(tmp_path: Path) -> None:
    from yas.info.shell_commands import main_inflight
    path = tmp_path / 't.jsonl'
    path.write_text('\n'.join([_use('t1', 'sleep 9', 5), _use('t2', 'ls', 6), _result('t2', 7)]) + '\n')
    assert [c for c, _ in main_inflight(str(path))] == ['sleep 9']


# ---- cached fold state from an older shape --------------------------------

def _fold_rec(cache: TranscriptCache, path: Path, key: str) -> dict:
    return next(iter(cache._entries[str(path)]['fold'][key].values()))


def test_subagent_fold_state_without_bash_is_refolded(tmp_home: Path) -> None:
    now = time.time()
    sdir = tmp_home / '.claude' / 'projects' / '-home-u-p' / 'sess' / 'subagents'
    sdir.mkdir(parents=True)
    (sdir / 'agent-a1.meta.json').write_text(json.dumps({'agentType': 'Explore', 'description': 'd'}))
    jsonl = sdir / 'agent-a1.jsonl'
    jsonl.write_text('\n'.join([_use('t1', 'sleep 30', now - 20)]) + '\n')

    cache = TranscriptCache('sess')
    subagents_mod.RunningSubagents.from_session('sess', '/home/u/p', now=now, cache=cache)

    # Rewrite the stored entry the way a pre-`bash` build left it: no `bash`
    # key in the state, no schema version on the record.
    rec = _fold_rec(cache, jsonl, 'parse')
    del rec['state']['bash']
    del rec['ver']
    cache.save()

    reloaded = TranscriptCache.load('sess')
    subs = subagents_mod.RunningSubagents.from_session('sess', '/home/u/p', now=now, cache=reloaded).subagents
    assert [c for c, _ in subs[0].bash_inflight] == ['sleep 30']
    assert 'bash' in _fold_rec(reloaded, jsonl, 'parse')['state']


def test_subagent_fold_state_without_bash_does_not_raise_when_read_directly(tmp_home: Path) -> None:
    now = time.time()
    sdir = tmp_home / '.claude' / 'projects' / '-home-u-p' / 'sess' / 'subagents'
    sdir.mkdir(parents=True)
    (sdir / 'agent-a1.meta.json').write_text(json.dumps({'agentType': 'Explore', 'description': 'd'}))
    (sdir / 'agent-a1.jsonl').write_text(_use('t1', 'ls', now - 5) + '\n')

    real = subagents_mod.parse_transcript_state

    def old_shape(*args, **kwargs):
        state = real(*args, **kwargs)
        state.pop('bash', None)
        return state

    subagents_mod.parse_transcript_state = old_shape
    try:
        subs = subagents_mod.RunningSubagents.from_session('sess', '/home/u/p', now=now).subagents
    finally:
        subagents_mod.parse_transcript_state = real
    assert subs[0].bash_inflight == ()


def test_main_inflight_survives_cached_state_without_calls(tmp_path: Path) -> None:
    from yas.info.shell_commands import main_inflight
    path = tmp_path / 't.jsonl'
    path.write_text(_use('t1', 'sleep 9', 5) + '\n')
    cache = TranscriptCache('sess')
    assert [c for c, _ in main_inflight(str(path), cache)] == ['sleep 9']

    _fold_rec(cache, path, 'shellflight')['state'].clear()
    with path.open('a') as f:
        f.write(_use('t2', 'sleep 8', 6) + '\n')
    assert [c for c, _ in main_inflight(str(path), cache)] == ['sleep 8']


def test_background_commands_survive_cached_state_without_cmds(tmp_path: Path) -> None:
    from yas.info.shell_commands import background_commands
    path = tmp_path / 't.jsonl'
    path.write_text(_use('t1', 'sleep 1', 5, bg=True) + '\n')
    cache = TranscriptCache('sess')
    assert background_commands(str(path), cache) == {'sleep 1'}

    _fold_rec(cache, path, 'shellbg')['state'].clear()
    with path.open('a') as f:
        f.write(_use('t2', 'sleep 2', 6, bg=True) + '\n')
    assert background_commands(str(path), cache) == {'sleep 2'}
