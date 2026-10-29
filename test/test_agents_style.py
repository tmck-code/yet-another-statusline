"""The `[shell_commands] style = "agents"` layout mode.

Main is always the first agent row; every row carries its command preview or
thinking state plus the shared cpu/mem/time columns. The separate shell
commands section is not rendered in this mode.
"""
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
from yas.config import Config, ShellCommandsConfig
from yas.constants import ICON_TERMINAL
from yas.info import SessionView
from yas.info.main_activity import MainActivity
from yas.info.shell_commands import MAIN_AGENT_ID, RunningShellCommands, ShellCommand
from yas.info.parsecache import TranscriptCache
from yas.render.text import _visible_width
from yas.tokens import TickRecord, TokenLog

_r = renderer_mod.Renderer()
SESSION = Path(__file__).parent.parent / 'ops' / 'session-info-example.json'
NOW = time.time()


def _cmd(command: str, *, elapsed: float = 72, cpu: float | None = 5.0,
         rss_kb: int = 20 * 1024) -> ShellCommand:
    return ShellCommand(pid=1, command=command, background=True, elapsed_s=elapsed,
                        cpu_percent=cpu, rss_kb=rss_kb)


def _sub(
    agent_type: str,
    *,
    commands: tuple[tuple[str, float], ...] = (),
    thinking_s: float | None = None,
    status: str = 'running',
    parent_id: str = '',
    start_ago: float = 120,
) -> subagents_mod.RunningSubagent:
    return subagents_mod.RunningSubagent(
        agent_type       = agent_type,
        description      = 'test desc',
        billed_in        = 1000,
        output           = 100,
        first_timestamp  = NOW - start_ago,
        model            = 'claude-sonnet-4-6',
        total_input      = 1000,
        last_activity    = ('thinking', '', {}) if thinking_s is not None else ('tool_use', 'Read', {}),
        last_activity_ts  = NOW - thinking_s if thinking_s is not None else 0.0,
        mtime            = NOW - 2,
        agent_id         = f'agent-{agent_type}',
        parent_id        = parent_id,
        status           = status,
        bash_inflight    = tuple((c, NOW - e) for c, e in commands),
    )


def _view(
    monkeypatch: pytest.MonkeyPatch,
    subs: list[subagents_mod.RunningSubagent],
    cmds: tuple[ShellCommand, ...] = (),
    *,
    activity: MainActivity | None = None,
    labels: bool = False,
    command_mode: str = 'chain',
) -> SessionView:
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir, **kw: subagents_mod.RunningSubagents(subagents=list(subs))),
    )
    monkeypatch.setattr(
        RunningShellCommands, 'from_session',
        classmethod(lambda cls, *a, **kw: RunningShellCommands(commands=cmds)),
    )
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    session.transcript_path = str(SESSION)  # existing file, so the gather is attempted
    view = SessionView(
        session,
        Config(labels=labels, shell_commands=ShellCommandsConfig(style='agents', command_mode=command_mode)),
        now=NOW,
    )
    view.__dict__['main_activity'] = activity or MainActivity(first_ts=NOW - 300, mtime=NOW - 1)
    return view


def _build(view: SessionView, width: int) -> layout.LayoutSpec:
    tick = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    if width >= 80:
        return layout.build_wide(view, tick, width, _r)
    if width >= 55:
        return layout.build_medium(view, width, _r)
    return layout.build_narrow(view, width, _r)


def _lines(view: SessionView, width: int) -> list[str]:
    return [strip_ansi(line) for line in layout.render_layout(_build(view, width), _r)]


def _agent_line(lines: list[str], name: str) -> str:
    return next(line for line in lines if re.search(rf'\b{re.escape(name)}\b', line))


@pytest.mark.parametrize('width', (50, 70, 140))
def test_main_is_always_first_and_present_without_subagents(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    lines = _lines(_view(monkeypatch, []), width)
    main = _agent_line(lines, 'main')
    assert 'main' in main
    assert {_visible_width(line) for line in lines} == {width}


@pytest.mark.parametrize('width', (50, 70, 140))
def test_main_row_precedes_subagent_rows(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    view = _view(monkeypatch, [_sub('worker-a')], (_cmd('make dev'),))
    lines = _lines(view, width)
    assert lines.index(_agent_line(lines, 'main')) < lines.index(_agent_line(lines, 'worker-a'))
    assert {_visible_width(line) for line in lines} == {width}


def test_resource_columns_align_across_main_and_subagents(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_sub('worker-a', commands=(('cargo build', 95),)), _sub('worker-b', thinking_s=8)]
    cmds = (
        _cmd('make dev', elapsed=120, cpu=5.0, rss_kb=20 * 1024),
        _cmd('cargo build', elapsed=95, cpu=8.0, rss_kb=30 * 1024),
    )
    lines = _lines(_view(monkeypatch, subs, cmds), 160)
    agent_rows = [_agent_line(lines, 'main'), _agent_line(lines, 'worker-a'), _agent_line(lines, 'worker-b')]
    for row in agent_rows:
        assert '%' in row
        assert 'M' in row
        assert re.search(r'\d+:\d{2}', row)
    assert len({row.index('%') for row in agent_rows}) == 1
    assert len({row.index('M', row.index('%')) for row in agent_rows}) == 1


def test_agents_style_uses_the_current_process_display(monkeypatch: pytest.MonkeyPatch) -> None:
    cmd = ShellCommand(
        pid=1, command='gate.sh make test | tail -4; grep x log',
        display_command='cargo test --test all generator::',
        background=False, elapsed_s=95, cpu_percent=43.0, rss_kb=6 * 1024,
    )
    row = _agent_line(_lines(_view(monkeypatch, [_sub('worker-a')], (cmd,)), 160), 'main')
    assert 'Bash[cargo test --test all generator::]' in row
    assert 'gate.sh' not in row
    assert '43%' in row


def test_agents_style_prefers_the_live_child_even_with_command_mode_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Agents rows are about current activity, so the default "chain" mode must
    # not leak the whole &&/;/| tool call into the preview.
    chain = 'cd /home/u/audiovis/.claude/worktrees/feat-mandala-promotion && git add -A backend-rs docs'
    cmd = ShellCommand(
        pid=1, command=chain, display_command='git add -A backend-rs docs',
        background=False, elapsed_s=95, cpu_percent=12.0, rss_kb=6 * 1024,
    )
    row = _agent_line(_lines(_view(monkeypatch, [_sub('worker-a')], (cmd,)), 160), 'main')
    assert 'Bash[git add -A backend-rs docs]' in row
    assert 'feat-mandala-promotion &&' not in row


def test_agents_style_falls_back_to_the_first_command_in_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No live child remains (for example the shell is between segments, or the
    # segment is a builtin such as `cd`): show that individual command, never
    # the whole &&-chain.
    chain = 'cd /home/u/audiovis/.claude/worktrees/feat-mandala-promotion && git add -A backend-rs docs'
    cmd = ShellCommand(
        pid=1, command=chain, background=False,
        elapsed_s=95, cpu_percent=12.0, rss_kb=6 * 1024,
    )
    row = _agent_line(_lines(_view(monkeypatch, [_sub('worker-a')], (cmd,)), 160), 'main')
    assert 'Bash[cd /home/u/audiovis/.claude/worktrees/feat-mandala-promotion]' in row
    assert '&&' not in row


def test_agents_style_always_gathers_in_current_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_from_session(cls, sid, transcript, cfg, **kw):
        seen['mode'] = cfg.command_mode
        return RunningShellCommands()

    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir, **kw: subagents_mod.RunningSubagents()),
    )
    monkeypatch.setattr(RunningShellCommands, 'from_session', classmethod(fake_from_session))
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    session.transcript_path = str(SESSION)
    view = SessionView(
        session,
        Config(shell_commands=ShellCommandsConfig(style='agents', command_mode='chain')),
        now=NOW,
    )
    assert view.shell_commands.count == 0
    assert seen['mode'] == 'current'



def test_thinking_subagent_shows_zero_resources_and_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_sub('worker-a', thinking_s=27)]
    lines = _lines(_view(monkeypatch, subs, (_cmd('make dev'),)), 160)
    row = _agent_line(lines, 'worker-a')
    assert '0%' in row and '0M' in row and '0:27' in row


def test_thinking_main_shows_zero_resources_and_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    activity = MainActivity(first_ts=NOW - 300, kind='thinking', since=NOW - 12, mtime=NOW - 1)
    view = _view(monkeypatch, [_sub('worker-a', commands=(('cargo build', 95),))],
                 (_cmd('cargo build', elapsed=95),), activity=activity)
    row = _agent_line(_lines(view, 160), 'main')
    assert '0%' in row and '0M' in row and '0:12' in row


def test_orchestrator_waiting_on_a_running_child_shows_zero_resources_and_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _sub('orchestrator', start_ago=140)
    parent.last_activity = ('text', 'dispatched the workers', {})
    child = _sub('worker', parent_id=parent.agent_id, start_ago=47)
    row = _agent_line(_lines(_view(monkeypatch, [parent, child], ()), 160), 'orchestrator')
    assert '✻ Waiting…' in row
    assert '0%' in row and '0M' in row
    assert '0:47' in row


def test_main_waiting_on_a_top_level_subagent_shows_zero_resources_and_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _sub('worker', start_ago=63)
    row = _agent_line(_lines(_view(monkeypatch, [child], ()), 160), 'main')
    assert '✻ Waiting…' in row
    assert '0%' in row and '0M' in row
    assert '1:03' in row


def test_parent_running_a_command_is_not_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _sub('orchestrator', commands=(('cargo build', 95),))
    parent.last_activity = ('tool_use', 'Bash', {'command': 'cargo build'})
    child = _sub('worker', parent_id=parent.agent_id, start_ago=47)
    view = _view(monkeypatch, [parent, child], (_cmd('cargo build', elapsed=95),), command_mode='current')
    row = _agent_line(_lines(view, 160), 'orchestrator')
    assert 'Bash[cargo build]' in row
    assert '✻ Waiting…' not in row


def test_running_agent_with_no_live_command_falls_back_to_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    # The transcript still carries the previous Bash tool_use as its last
    # activity; with no live process the agent is processing, not still running
    # that tool.
    sub = _sub('worker-a')
    sub.last_activity = ('tool_use', 'Bash', {'command': 'cargo test'})
    lines = _lines(_view(monkeypatch, [sub]), 160)
    row = _agent_line(lines, 'worker-a')
    assert '✻ Thinking…' in row
    assert '0%' in row and '0M' in row
    assert re.search(r'0:0[1-3]', row)


def test_multiple_commands_aggregate_and_show_plus_n(monkeypatch: pytest.MonkeyPatch) -> None:
    sub = _sub('worker-a', commands=(('cargo build', 95), ('cargo test', 120)))
    sub.last_activity = ('tool_use', 'Bash', {'command': 'cargo test'})
    cmds = (
        _cmd('cargo build', elapsed=95, cpu=5.0, rss_kb=20 * 1024),
        _cmd('cargo test', elapsed=120, cpu=10.0, rss_kb=30 * 1024),
    )
    row = _agent_line(_lines(_view(monkeypatch, [sub], cmds), 160), 'worker-a')
    assert 'Bash[cargo test] +1' in row
    assert '15%' in row
    assert '2:00' in row


def test_separate_shell_commands_section_is_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_sub('worker-a'), _sub('worker-b')]
    cmds = (_cmd('make dev'), _cmd('cargo build'), _cmd('sleep 5'))
    lines = _lines(_view(monkeypatch, subs, cmds), 160)
    assert not any('shell commands' in line for line in lines)
    assert not any(ICON_TERMINAL in line for line in lines)
    assert 'bg' not in '\n'.join(lines)


def test_unattributed_command_stays_on_main_row(monkeypatch: pytest.MonkeyPatch) -> None:
    sub = _sub('worker-a', commands=(('cargo build', 95),))
    sub.last_activity = ('tool_use', 'Bash', {'command': 'cargo build'})
    subs = [sub]
    cmds = (_cmd('cargo build', elapsed=95), _cmd('make dev', elapsed=120))
    lines = _lines(_view(monkeypatch, subs, cmds), 160)
    assert 'Bash[make dev]' in _agent_line(lines, 'main')
    assert 'Bash[cargo build]' in _agent_line(lines, 'worker-a')


def test_current_non_bash_tool_call_is_shown_even_with_owned_background_bash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A background/long-running Bash process must not hide what the agent is
    # doing now: the activity column carries the current Write call, while the
    # resource columns still reflect the owned process.
    sub = _sub('worker-a', commands=(('cargo build', 95),))
    sub.last_activity = ('tool_use', 'Write', {'file_path': '/repo/src/main.py'})
    cmds = (_cmd('cargo build', elapsed=95, cpu=12.0, rss_kb=100 * 1024),)
    row = _agent_line(_lines(_view(monkeypatch, [sub], cmds), 160), 'worker-a')
    assert 'Write[main.py]' in row
    assert 'Bash[' not in row
    assert '12%' in row and '100M' in row and '1:35' in row


def test_thinking_is_not_masked_by_an_owned_background_bash_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub = _sub('worker-a', commands=(('cargo build', 95),), thinking_s=27)
    cmds = (_cmd('cargo build', elapsed=95, cpu=12.0, rss_kb=100 * 1024),)
    row = _agent_line(_lines(_view(monkeypatch, [sub], cmds), 160), 'worker-a')
    assert '✻ Thinking…' in row
    assert 'Bash[' not in row
    # The process still drives the resource columns.
    assert '12%' in row and '100M' in row


def test_current_bash_call_shows_the_live_child_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub = _sub('worker-a', commands=(('cargo build', 95),))
    sub.last_activity = ('tool_use', 'Bash', {'command': 'cargo build'})
    cmd = ShellCommand(
        pid=1, command='cargo build', background=False,
        elapsed_s=95, cpu_percent=12.0, rss_kb=6 * 1024,
        live_command='rustc --crate-name yas',
    )
    row = _agent_line(_lines(_view(monkeypatch, [sub], (cmd,)), 160), 'worker-a')
    assert 'Bash[rustc --crate-name yas]' in row
    assert 'cargo build' not in row


@pytest.mark.parametrize(
    ('tool', 'tool_input', 'shown'),
    (
        ('Read',  {'file_path': '/repo/src/main.py'}, 'Read[main.py]'),
        ('Write', {'file_path': '/repo/src/main.py'}, 'Write[main.py]'),
        ('Edit',  {'file_path': '/repo/src/main.py'}, 'Edit[main.py]'),
        ('Grep',  {'pattern': 'def main'}, 'Grep[def main]'),
    ),
)
def test_main_current_non_bash_tool_call_is_shown_even_with_owned_background_bash(
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    tool_input: dict[str, object],
    shown: str,
) -> None:
    # The background Bash process must not hide what main is doing now: the
    # activity column carries the current tool call, while cpu/mem/time still
    # reflect the owned process.
    activity = MainActivity(
        first_ts=NOW - 300, kind='tool_use', since=NOW - 1, mtime=NOW - 1,
        activity=('tool_use', tool, tool_input),
    )
    cmds = (_cmd('cargo build', elapsed=95, cpu=12.0, rss_kb=100 * 1024),)
    row = _agent_line(_lines(_view(monkeypatch, [], cmds, activity=activity), 160), 'main')
    assert shown in row
    assert 'Bash[' not in row
    assert '12%' in row and '100M' in row and '1:35' in row


def test_main_current_bash_call_shows_the_live_child_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activity = MainActivity(
        first_ts=NOW - 300, kind='tool_use', since=NOW - 1, mtime=NOW - 1,
        activity=('tool_use', 'Bash', {'command': 'cargo build'}),
    )
    cmd = ShellCommand(
        pid=1, command='cargo build', background=False,
        elapsed_s=95, cpu_percent=12.0, rss_kb=6 * 1024,
        live_command='rustc --crate-name yas',
    )
    row = _agent_line(_lines(_view(monkeypatch, [], (cmd,), activity=activity), 160), 'main')
    assert 'Bash[rustc --crate-name yas]' in row
    assert 'cargo build' not in row


def test_main_thinking_is_not_masked_by_an_owned_background_bash_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activity = MainActivity(
        first_ts=NOW - 300, kind='thinking', since=NOW - 12, mtime=NOW - 1,
        activity=('thinking', '', {}),
    )
    cmds = (_cmd('cargo build', elapsed=95, cpu=12.0, rss_kb=100 * 1024),)
    row = _agent_line(_lines(_view(monkeypatch, [], cmds, activity=activity), 160), 'main')
    assert '✻ Thinking…' in row
    assert 'Bash[' not in row
    # The owned process still drives the resource columns (and their timers).
    assert '12%' in row and '100M' in row and '1:35' in row


def test_labels_mark_the_agent_and_resource_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    sub = _sub('worker-a', commands=(('cargo build', 95),))
    sub.last_activity = ('tool_use', 'Bash', {'command': 'cargo build'})
    view = _view(monkeypatch, [sub], (_cmd('cargo build', elapsed=95),), labels=True)
    lines = _lines(view, 160)
    sep = next(line for line in lines if 'ᵃᵍᵉⁿᵗ' in line)
    assert 'ᶜᵖᵘ' in sep and 'ᵐᵉᵐ' in sep and 'ᵗⁱᵐᵉ' in sep


def test_older_cached_fold_without_activity_timestamp_is_refolded(tmp_home: Path) -> None:
    sdir = tmp_home / '.claude' / 'projects' / '-home-u-p' / 'sess' / 'subagents'
    sdir.mkdir(parents=True)
    (sdir / 'agent-a1.meta.json').write_text(json.dumps({'agentType': 'Explore', 'description': 'd'}))
    thinking_ts = NOW - 27
    jsonl = sdir / 'agent-a1.jsonl'
    jsonl.write_text(json.dumps({
        'type': 'assistant',
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(thinking_ts)),
        'message': {
            'id': 'msg-think',
            'role': 'assistant',
            'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 0,
                      'cache_read_input_tokens': 0, 'output_tokens': 5},
            'content': [{'type': 'thinking', 'thinking': 'pondering'}],
        },
    }) + '\n')

    cache = TranscriptCache('sess')
    subs = subagents_mod.RunningSubagents.from_session('sess', '/home/u/p', now=NOW, cache=cache).subagents
    assert subs[0].last_activity[0] == 'thinking'
    assert subs[0].last_activity_ts > 0

    rec = next(iter(cache._entries[str(jsonl)]['fold']['parse'].values()))
    rec['state']['cur'].pop('ts', None)
    rec.pop('ver', None)
    cache.save()

    reloaded = TranscriptCache.load('sess')
    rebuilt = subagents_mod.RunningSubagents.from_session('sess', '/home/u/p', now=NOW, cache=reloaded).subagents
    assert rebuilt[0].last_activity[0] == 'thinking'
    assert rebuilt[0].last_activity_ts > 0
    new_rec = next(iter(reloaded._entries[str(jsonl)]['fold']['parse'].values()))
    assert 'ts' in new_rec['state']['cur']


def test_main_agent_id_is_reserved() -> None:
    assert MAIN_AGENT_ID == '__main__'
