"""Per-subagent resource columns: ownership matching, shell section split, row display."""
import json
import time
from pathlib import Path

import pytest

import yas.info.subagents as subagents_mod
import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
from helper import iso_ts, strip_ansi
from yas.config import AgentsConfig, Config, ResourceUsageConfig, ShellCommandsConfig
from yas.constants import CLR_WARN, SHELL_COL_GAP
from yas.info import SessionView
from yas.info.bash_inflight import fold_line, inflight
from yas.info.parsecache import TranscriptCache
from yas.info.shell_commands import AgentUsage, RunningShellCommands, ShellCommand, split_by_owner
from yas.render.text import _visible_width
from yas.tokens import TickRecord, TokenLog

_r = renderer_mod.Renderer()
SESSION = Path(__file__).parent.parent / 'ops' / 'session-info-example.json'
NOW = 100_000.0


def _cmd(command: str, *, elapsed: float = 60, cpu: float | None = 5.0, rss_kb: int = 20 * 1024) -> ShellCommand:
    return ShellCommand(pid=1, command=command, background=False, elapsed_s=elapsed,
                        cpu_percent=cpu, rss_kb=rss_kb)


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


def test_command_matching_an_in_flight_call_is_owned() -> None:
    mine, theirs = _split([_cmd('sleep 30', elapsed=20)], {'a1': (('sleep 30', NOW - 21),)})
    assert mine == ()
    assert [c.command for c in theirs['a1']] == ['sleep 30']


def test_command_without_a_matching_call_stays_with_main() -> None:
    mine, theirs = _split([_cmd('sleep 30')], {'a1': (('sleep 99', NOW - 20),)})
    assert len(mine) == 1
    assert theirs == {}


def test_identical_command_resolves_to_closest_start_time() -> None:
    owners = {'a1': (('make', NOW - 500),), 'a2': (('make', NOW - 61),)}
    _, theirs = _split([_cmd('make', elapsed=60)], owners)
    assert list(theirs) == ['a2']


def test_subagent_beats_main_when_its_call_started_closer() -> None:
    mine, theirs = _split([_cmd('make', elapsed=60)], {'a1': (('make', NOW - 61),)}, main=[('make', NOW - 900)])
    assert mine == ()
    assert list(theirs) == ['a1']


def test_main_keeps_command_when_its_call_started_closer() -> None:
    mine, theirs = _split([_cmd('make', elapsed=60)], {'a1': (('make', NOW - 900),)}, main=[('make', NOW - 61)])
    assert len(mine) == 1
    assert theirs == {}


def test_ambiguous_owners_leave_command_in_shell_section() -> None:
    owners = {'a1': (('make', NOW - 61),), 'a2': (('make', NOW - 61.2),)}
    mine, theirs = _split([_cmd('make', elapsed=60)], owners)
    assert len(mine) == 1
    assert theirs == {}


def test_one_call_is_claimed_by_one_process() -> None:
    cmds = [_cmd('make', elapsed=60), _cmd('make', elapsed=10)]
    mine, theirs = _split(cmds, {'a1': (('make', NOW - 61),)})
    assert [c.elapsed_s for c in mine] == [10]
    assert [c.elapsed_s for c in theirs['a1']] == [60]


# ---- view split -----------------------------------------------------------

def _sub(agent_id: str, calls=(), activity: str = 'pytest', status: str = 'running') -> subagents_mod.RunningSubagent:
    now = time.time()
    return subagents_mod.RunningSubagent(
        agent_type=agent_id, description='test desc', billed_in=1000, output=100,
        first_timestamp=now - 10, model='claude-sonnet-4-6', total_input=1000,
        last_activity=('tool_use', 'Bash', {'command': activity}), mtime=now - 5,
        agent_id=agent_id, status=status, bash_inflight=tuple(calls),
    )


def _view(monkeypatch: pytest.MonkeyPatch, subs, cmds, *, labels: bool = False, usage: dict | None = None,
          agents: AgentsConfig | None = None, shell: ShellCommandsConfig | None = None) -> SessionView:
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir, **kw: subagents_mod.RunningSubagents(subagents=list(subs))),
    )
    monkeypatch.setattr(
        RunningShellCommands, 'from_session',
        classmethod(lambda cls, *a, **kw: RunningShellCommands(commands=tuple(cmds))),
    )
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    session.transcript_path = str(SESSION)
    cfg = Config(labels=labels, shell_commands=shell or ShellCommandsConfig(style='list', position='below'),
                 agents=agents or AgentsConfig())
    return SessionView(session, cfg, now=NOW)


def _owned_view(monkeypatch, **kw) -> SessionView:
    t = NOW - 21
    subs = [_sub('a1', [('sleep 30', t)]), _sub('a2')]
    cmds = [_cmd('sleep 30', elapsed=20, cpu=12.0, rss_kb=100 * 1024), _cmd('make demo', elapsed=5)]
    return _view(monkeypatch, subs, cmds, **kw)


def test_shell_section_excludes_owned_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _owned_view(monkeypatch)
    assert [c.command for c in view.shell_commands.commands] == ['make demo']
    assert set(view.subagent_usage) == {'a1'}


def test_usage_sums_cpu_and_memory_and_takes_longest_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_sub('a1', [('x', NOW - 100), ('y', NOW - 31)])]
    cmds = [_cmd('x', elapsed=99, cpu=10.0, rss_kb=1024), _cmd('y', elapsed=30, cpu=2.5, rss_kb=2048)]
    usage = _view(monkeypatch, subs, cmds).subagent_usage['a1']
    assert (usage.cpu_percent, usage.rss_kb, usage.elapsed_s) == (12.5, 3072, 99)


def test_shell_section_hidden_when_all_processes_are_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _view(monkeypatch, [_sub('a1', [('sleep 30', NOW - 21)])], [_cmd('sleep 30', elapsed=20)])
    assert not view.shell_commands
    assert view.shell_commands.count == 0


def test_disabled_resource_usage_keeps_processes_in_shell_section(monkeypatch: pytest.MonkeyPatch) -> None:
    agents = AgentsConfig(resource_usage=ResourceUsageConfig(enabled=False))
    view = _owned_view(monkeypatch, agents=agents)
    assert view.shell_commands.count == 2
    assert view.subagent_usage == {}


def test_finished_subagent_does_not_own_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _view(monkeypatch, [_sub('a1', [('sleep 30', NOW - 21)], status='completed')], [_cmd('sleep 30', elapsed=20)])
    assert view.shell_commands.count == 1


# ---- row display ----------------------------------------------------------

def _build(view: SessionView, width: int) -> layout.LayoutSpec:
    tick = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    if width >= 120:
        return layout.build_wide(view, tick, width, _r)
    return layout.build_narrow(view, width, _r)


def _contents(spec: layout.LayoutSpec) -> list[str]:
    return [row.content for row in spec.rows if row.kind == 'content']


def _agent_rows(spec: layout.LayoutSpec) -> list[str]:
    return [strip_ansi(c) for c in _contents(spec) if 'a1' in strip_ansi(c) or 'a2' in strip_ansi(c)]


def _block_widths(spec: layout.LayoutSpec) -> set[int]:
    'Visible widths of the subagent and shell rows (the other rows are sized elsewhere).'
    keep = ('a1', 'a2', 'shell commands', 'fg ', 'bg ')
    return {_visible_width(c) for c in _contents(spec) if any(k in strip_ansi(c) for k in keep)}


@pytest.mark.parametrize('width', (80, 140, 200))
def test_owning_row_shows_cpu_mem_elapsed_and_other_row_is_blank(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    rows = _agent_rows(_build(_owned_view(monkeypatch), width))
    own = next(r for r in rows if 'a1' in r)
    other = next(r for r in rows if 'a2' in r)
    assert own.rstrip().endswith('12%  100M  0:20')
    assert not other.rstrip().endswith('0:20')
    assert _visible_width(own) == _visible_width(other)


@pytest.mark.parametrize('width', (80, 140, 200))
def test_columns_align_across_rows(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    subs = [_sub('a1', [('x', NOW - 100)]), _sub('a2', [('y', NOW - 4000)])]
    cmds = [_cmd('x', elapsed=99, cpu=3.0, rss_kb=5 * 1024), _cmd('y', elapsed=3990, cpu=250.0, rss_kb=2048 * 1024)]
    rows = _agent_rows(_build(_view(monkeypatch, subs, cmds), width))
    assert len(rows) == 2
    assert len({len(r.rstrip()) for r in rows}) == 1
    assert rows[0].rstrip().endswith('  3%    5M     1:39')
    assert rows[1].rstrip().endswith('250%  2.0G  1:06:30')


@pytest.mark.parametrize('width', (80, 140, 200))
def test_all_content_rows_keep_the_same_visible_width(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    spec = _build(_owned_view(monkeypatch, labels=True), width)
    assert len(_block_widths(spec)) == 1


def test_warn_colour_uses_shell_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    shell = ShellCommandsConfig(cpu=ShellCommandsConfig().cpu._replace(warn_percent=10.0))
    own = next(c for c in _contents(_build(_owned_view(monkeypatch, shell=shell), 140)) if 'a1' in strip_ansi(c))
    assert f'{CLR_WARN}12%' in own


def test_labels_are_painted_over_the_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _build(_owned_view(monkeypatch, labels=True), 200)
    sep = next(row for row in spec.rows if any(name == 'cpu' for name, _ in row.labels))
    cols = dict(sep.labels)
    assert {'cpu', 'mem', 'time', 'agent'} <= set(cols)
    data = next(strip_ansi(c) for c in _contents(spec) if 'a1' in strip_ansi(c))
    # a label is right-aligned over its column; its last char sits over the value's last char
    # (border column - 3 is the content offset)
    assert data[cols['time'] - 3 + len('time') - 1] == '0'
    assert data[cols['cpu'] - 3 + len('cpu') - 1] == '%'
    assert cols['cpu'] < cols['mem'] < cols['time']


def test_disabled_columns_are_omitted_with_their_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    agents = AgentsConfig(resource_usage=ResourceUsageConfig(memory=False, elapsed=False))
    spec = _build(_owned_view(monkeypatch, labels=True, agents=agents), 200)
    names = set(next(dict(row.labels) for row in spec.rows if any(n == 'cpu' for n, _ in row.labels)))
    assert {'agent', 'cpu'} <= names
    assert not names & {'mem', 'time'}
    own = next(strip_ansi(c) for c in _contents(spec) if 'a1' in strip_ansi(c))
    assert own.rstrip().endswith('12%')


def test_no_columns_reserved_without_an_owned_process(monkeypatch: pytest.MonkeyPatch) -> None:
    plain = _agent_rows(_build(_view(monkeypatch, [_sub('a1'), _sub('a2')], [_cmd('make demo')]), 140))
    assert all(r.rstrip().endswith('Bash[pytest]') for r in plain)


def test_activity_column_truncates_to_make_room(monkeypatch: pytest.MonkeyPatch) -> None:
    long = 'x' * 120
    view = _view(monkeypatch, [_sub('a1', [('sleep 30', NOW - 21)], activity=long), _sub('a2', activity=long)],
                 [_cmd('sleep 30', elapsed=20)])
    rows = _agent_rows(_build(view, 140))
    assert all('…' in r or 'x' * 120 not in r for r in rows)
    assert rows[0].rstrip().endswith('0:20')


def test_side_section_is_balanced_and_keeps_owned_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    shell = ShellCommandsConfig(style='list', position='right')
    view = _owned_view(monkeypatch, labels=True, shell=shell)
    spec = _build(view, 200)
    assert len(_block_widths(spec)) == 1
    plain = [strip_ansi(c) for c in _contents(spec)]
    assert any('a1' in p and '12%' in p and '│' in p for p in plain)
    assert any('shell commands (1)' in p or 'make demo' in p for p in plain)


def test_columns_omitted_when_the_row_would_fall_below_its_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _agent_rows(_build(_owned_view(monkeypatch), 40))
    assert rows
    assert not any('12%' in r for r in rows)


def test_plan_gap_matches_shell_section(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _r.agent_usage_plan(
        {'a1': AgentUsage(cpu_percent=12.0, rss_kb=100 * 1024, elapsed_s=20)},
        ShellCommandsConfig(), ResourceUsageConfig(), labelled=False,
    )
    assert plan is not None
    assert plan.width == SHELL_COL_GAP + _visible_width(strip_ansi(plan.cells['a1']))
    assert strip_ansi(plan.cells['a1']) == '12%  100M  0:20'


@pytest.mark.parametrize('width', (80, 140, 200))
def test_badge_sits_right_of_the_columns_on_the_first_row(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    shell = ShellCommandsConfig(style='badge', position='right')
    spec = _build(_owned_view(monkeypatch, shell=shell), width)
    own = next(strip_ansi(c) for c in _contents(spec) if 'a1' in strip_ansi(c))
    assert own.index('12%') < own.index('\uf120')
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
