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
from helper import strip_ansi
from yas.config import Config, ShellCommandsConfig
from yas.constants import ICON_TERMINAL
from yas.info import SessionView
from yas.info.main_activity import MainActivity
from yas.info.shell_commands import MAIN_AGENT_ID, RunningShellCommands
from yas.info.parsecache import TranscriptCache
from yas.render.text import _visible_width
from yas.renderer import Renderer
from yas.tokens import TickRecord, TokenLog

NOW = time.time()


@pytest.fixture
def make_sub(make_subagent):
    def make(agent_type: str, **kw) -> subagents_mod.RunningSubagent:
        return make_subagent(agent_type, now=NOW, **kw)
    return make


@pytest.fixture
def build_view(make_view):
    def make(
        subs: list[subagents_mod.RunningSubagent],
        cmds=(),
        *,
        activity: MainActivity | None = None,
        labels: bool = False,
        command_mode: str = 'chain',
    ) -> SessionView:
        return make_view(
            cfg      = Config(labels=labels, shell_commands=ShellCommandsConfig(style='agents', command_mode=command_mode)),
            subs     = subs,
            commands = tuple(cmds),
            now      = NOW,
            main_activity = activity or MainActivity(first_ts=NOW - 300, mtime=NOW - 1),
        )
    return make


def _build(view: SessionView, width: int, renderer: Renderer) -> layout.LayoutSpec:
    tick = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    if width >= 80:
        return layout.build_wide(view, tick, width, renderer)
    if width >= 55:
        return layout.build_medium(view, width, renderer)
    return layout.build_narrow(view, width, renderer)


def _lines(view: SessionView, width: int, renderer: Renderer) -> list[str]:
    return [strip_ansi(line) for line in layout.render_layout(_build(view, width, renderer), renderer)]


def _agent_line(lines: list[str], name: str) -> str:
    return next(line for line in lines if re.search(rf'\b{re.escape(name)}\b', line))


@pytest.mark.parametrize('width', (50, 70, 140))
def test_main_is_always_first_and_present_without_subagents(monkeypatch: pytest.MonkeyPatch, width: int, renderer, build_view) -> None:
    lines = _lines(build_view([]), width, renderer)
    main = _agent_line(lines, 'main')
    assert 'main' in main
    assert {_visible_width(line) for line in lines} == {width}


@pytest.mark.parametrize('width', (50, 70, 140))
def test_main_row_precedes_subagent_rows(monkeypatch: pytest.MonkeyPatch, width: int, renderer, build_view, make_sub, make_shell_command) -> None:
    view = build_view([make_sub('worker-a')], (make_shell_command('make dev'),))
    lines = _lines(view, width, renderer)
    assert lines.index(_agent_line(lines, 'main')) < lines.index(_agent_line(lines, 'worker-a'))
    assert {_visible_width(line) for line in lines} == {width}


def test_resource_columns_align_across_main_and_subagents(monkeypatch: pytest.MonkeyPatch, renderer, build_view, make_sub, make_shell_command) -> None:
    subs = [make_sub('worker-a', commands=(('cargo build', 95),)), make_sub('worker-b', thinking_s=8)]
    cmds = (
        make_shell_command('make dev', elapsed=120, cpu=5.0, rss_kb=20 * 1024),
        make_shell_command('cargo build', elapsed=95, cpu=8.0, rss_kb=30 * 1024),
    )
    lines = _lines(build_view(subs, cmds), 160, renderer)
    agent_rows = [_agent_line(lines, 'main'), _agent_line(lines, 'worker-a'), _agent_line(lines, 'worker-b')]
    for row in agent_rows:
        assert '%' in row
        assert 'M' in row
        assert re.search(r'\d+:\d{2}', row)
    assert len({row.index('%') for row in agent_rows}) == 1
    assert len({row.index('M', row.index('%')) for row in agent_rows}) == 1


def test_agents_style_uses_the_current_process_display(monkeypatch: pytest.MonkeyPatch, renderer, build_view, make_sub, make_shell_command) -> None:
    cmd = make_shell_command(
        'gate.sh make test | tail -4; grep x log',
        display_command='cargo test --test all generator::',
        background=False, elapsed=95, cpu=43.0, rss_kb=6 * 1024,
    )
    row = _agent_line(_lines(build_view([make_sub('worker-a')], (cmd,)), 160, renderer), 'main')
    assert 'Bash[cargo test --test all generator::]' in row
    assert 'gate.sh' not in row
    assert '43%' in row


def test_agents_style_prefers_the_live_child_even_with_command_mode_chain(
    monkeypatch: pytest.MonkeyPatch,
    renderer, build_view, make_sub, make_shell_command,
) -> None:
    # Agents rows are about current activity, so the default "chain" mode must
    # not leak the whole &&/;/| tool call into the preview.
    chain = 'cd /home/u/audiovis/.claude/worktrees/feat-mandala-promotion && git add -A backend-rs docs'
    cmd = make_shell_command(
        chain, display_command='git add -A backend-rs docs',
        background=False, elapsed=95, cpu=12.0, rss_kb=6 * 1024,
    )
    row = _agent_line(_lines(build_view([make_sub('worker-a')], (cmd,)), 160, renderer), 'main')
    assert 'Bash[git add -A backend-rs docs]' in row
    assert 'feat-mandala-promotion &&' not in row


def test_agents_style_falls_back_to_the_first_command_in_the_chain(
    monkeypatch: pytest.MonkeyPatch,
    renderer, build_view, make_sub, make_shell_command,
) -> None:
    # No live child remains (for example the shell is between segments, or the
    # segment is a builtin such as `cd`): show that individual command, never
    # the whole &&-chain.
    chain = 'cd /home/u/audiovis/.claude/worktrees/feat-mandala-promotion && git add -A backend-rs docs'
    cmd = make_shell_command(
        chain, background=False, elapsed=95, cpu=12.0, rss_kb=6 * 1024,
    )
    row = _agent_line(_lines(build_view([make_sub('worker-a')], (cmd,)), 160, renderer), 'main')
    assert 'Bash[cd /home/u/audiovis/.claude/worktrees/feat-mandala-promotion]' in row
    assert '&&' not in row


def test_agents_style_always_gathers_in_current_mode(make_view) -> None:
    seen: dict[str, str] = {}

    def fake_from_session(cls, sid, transcript, cfg, **kw):
        seen['mode'] = cfg.command_mode
        return RunningShellCommands()

    view = make_view(
        cfg=Config(shell_commands=ShellCommandsConfig(style='agents', command_mode='chain')),
        now=NOW,
        shell_from_session=fake_from_session,
    )
    assert view.shell_commands.count == 0
    assert seen['mode'] == 'current'



def test_thinking_subagent_shows_zero_resources_and_timer(monkeypatch: pytest.MonkeyPatch, renderer, build_view, make_sub, make_shell_command) -> None:
    subs = [make_sub('worker-a', thinking_s=27)]
    lines = _lines(build_view(subs, (make_shell_command('make dev'),)), 160, renderer)
    row = _agent_line(lines, 'worker-a')
    assert '0%' in row and '0M' in row and '0:27' in row


def test_thinking_main_shows_zero_resources_and_timer(monkeypatch: pytest.MonkeyPatch, renderer, build_view, make_sub, make_shell_command) -> None:
    activity = MainActivity(first_ts=NOW - 300, kind='thinking', since=NOW - 12, mtime=NOW - 1)
    view = build_view([make_sub('worker-a', commands=(('cargo build', 95),))],
                 (make_shell_command('cargo build', elapsed=95),), activity=activity)
    row = _agent_line(_lines(view, 160, renderer), 'main')
    assert '0%' in row and '0M' in row and '0:12' in row


@pytest.mark.parametrize(
    ('kind', 'activity'),
    (
        ('text', ('text', 'here is the answer', {})),
        ('tool_use', ('tool_use', 'Read', {'file_path': '/repo/x.py'})),
        ('', ('', '', {})),
    ),
)
def test_non_thinking_main_does_not_show_a_thinking_timer(
    kind: str, activity: tuple[str, str, dict[str, object]], renderer, build_view,
) -> None:
    main = MainActivity(first_ts=NOW - 300, kind=kind, since=NOW - 12, mtime=NOW - 1, activity=activity)
    row = _agent_line(_lines(build_view([], activity=main), 160, renderer), 'main')
    assert 'Thinking' not in row
    assert '0%' not in row


def test_orchestrator_waiting_on_a_running_child_shows_zero_resources_and_timer(
    monkeypatch: pytest.MonkeyPatch,
    renderer, build_view, make_sub,
) -> None:
    parent = make_sub('orchestrator', start_ago=140)
    parent.last_activity = ('text', 'dispatched the workers', {})
    child = make_sub('worker', parent_id=parent.agent_id, start_ago=47)
    row = _agent_line(_lines(build_view([parent, child], ()), 160, renderer), 'orchestrator')
    assert '✻ Waiting…' in row
    assert '0%' in row and '0M' in row
    assert '0:47' in row


def test_main_waiting_on_a_top_level_subagent_shows_zero_resources_and_timer(
    monkeypatch: pytest.MonkeyPatch,
    renderer, build_view, make_sub,
) -> None:
    child = make_sub('worker', start_ago=63)
    row = _agent_line(_lines(build_view([child], ()), 160, renderer), 'main')
    assert '✻ Waiting…' in row
    assert '0%' in row and '0M' in row
    assert '1:03' in row


def test_parent_running_a_command_is_not_waiting(monkeypatch: pytest.MonkeyPatch, renderer, build_view, make_sub, make_shell_command) -> None:
    parent = make_sub('orchestrator', commands=(('cargo build', 95),))
    parent.last_activity = ('tool_use', 'Bash', {'command': 'cargo build'})
    child = make_sub('worker', parent_id=parent.agent_id, start_ago=47)
    view = build_view([parent, child], (make_shell_command('cargo build', elapsed=95),), command_mode='current')
    row = _agent_line(_lines(view, 160, renderer), 'orchestrator')
    assert 'Bash[cargo build]' in row
    assert '✻ Waiting…' not in row


def test_running_agent_with_no_live_command_falls_back_to_thinking(monkeypatch: pytest.MonkeyPatch, renderer, build_view, make_sub) -> None:
    # The transcript still carries the previous Bash tool_use as its last
    # activity; with no live process the agent is processing, not still running
    # that tool.
    sub = make_sub('worker-a')
    sub.last_activity = ('tool_use', 'Bash', {'command': 'cargo test'})
    lines = _lines(build_view([sub]), 160, renderer)
    row = _agent_line(lines, 'worker-a')
    assert '✻ Thinking…' in row
    assert '0%' in row and '0M' in row
    assert re.search(r'0:0[1-3]', row)


def test_multiple_commands_aggregate_and_show_plus_n(monkeypatch: pytest.MonkeyPatch, renderer, build_view, make_sub, make_shell_command) -> None:
    sub = make_sub('worker-a', commands=(('cargo build', 95), ('cargo test', 120)))
    sub.last_activity = ('tool_use', 'Bash', {'command': 'cargo test'})
    cmds = (
        make_shell_command('cargo build', elapsed=95, cpu=5.0, rss_kb=20 * 1024),
        make_shell_command('cargo test', elapsed=120, cpu=10.0, rss_kb=30 * 1024),
    )
    row = _agent_line(_lines(build_view([sub], cmds), 160, renderer), 'worker-a')
    assert 'Bash[cargo test] +1' in row
    assert '15%' in row
    assert '2:00' in row


def test_separate_shell_commands_section_is_hidden(monkeypatch: pytest.MonkeyPatch, renderer, build_view, make_sub, make_shell_command) -> None:
    subs = [make_sub('worker-a'), make_sub('worker-b')]
    cmds = (make_shell_command('make dev'), make_shell_command('cargo build'), make_shell_command('sleep 5'))
    lines = _lines(build_view(subs, cmds), 160, renderer)
    assert not any('shell commands' in line for line in lines)
    assert not any(ICON_TERMINAL in line for line in lines)
    assert 'bg' not in '\n'.join(lines)


def test_unattributed_command_stays_on_main_row(monkeypatch: pytest.MonkeyPatch, renderer, build_view, make_sub, make_shell_command) -> None:
    sub = make_sub('worker-a', commands=(('cargo build', 95),))
    sub.last_activity = ('tool_use', 'Bash', {'command': 'cargo build'})
    subs = [sub]
    cmds = (make_shell_command('cargo build', elapsed=95), make_shell_command('make dev', elapsed=120))
    lines = _lines(build_view(subs, cmds), 160, renderer)
    assert 'Bash[make dev]' in _agent_line(lines, 'main')
    assert 'Bash[cargo build]' in _agent_line(lines, 'worker-a')


def test_current_non_bash_tool_call_is_shown_even_with_owned_background_bash(
    monkeypatch: pytest.MonkeyPatch,
    renderer, build_view, make_sub, make_shell_command,
) -> None:
    # A background/long-running Bash process must not hide what the agent is
    # doing now: the activity column carries the current Write call, while the
    # resource columns still reflect the owned process.
    sub = make_sub('worker-a', commands=(('cargo build', 95),))
    sub.last_activity = ('tool_use', 'Write', {'file_path': '/repo/src/main.py'})
    cmds = (make_shell_command('cargo build', elapsed=95, cpu=12.0, rss_kb=100 * 1024),)
    row = _agent_line(_lines(build_view([sub], cmds), 160, renderer), 'worker-a')
    assert 'Write[main.py]' in row
    assert 'Bash[' not in row
    assert '12%' in row and '100M' in row and '1:35' in row


def test_thinking_is_not_masked_by_an_owned_background_bash_process(
    monkeypatch: pytest.MonkeyPatch,
    renderer, build_view, make_sub, make_shell_command,
) -> None:
    sub = make_sub('worker-a', commands=(('cargo build', 95),), thinking_s=27)
    cmds = (make_shell_command('cargo build', elapsed=95, cpu=12.0, rss_kb=100 * 1024),)
    row = _agent_line(_lines(build_view([sub], cmds), 160, renderer), 'worker-a')
    assert '✻ Thinking…' in row
    assert 'Bash[' not in row
    # The process still drives the resource columns.
    assert '12%' in row and '100M' in row


def test_current_bash_call_shows_the_live_child_command(
    monkeypatch: pytest.MonkeyPatch,
    renderer, build_view, make_sub, make_shell_command,
) -> None:
    sub = make_sub('worker-a', commands=(('cargo build', 95),))
    sub.last_activity = ('tool_use', 'Bash', {'command': 'cargo build'})
    cmd = make_shell_command(
        'cargo build', background=False, elapsed=95, cpu=12.0, rss_kb=6 * 1024,
        live_command='rustc --crate-name yas',
    )
    row = _agent_line(_lines(build_view([sub], (cmd,)), 160, renderer), 'worker-a')
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
    renderer, build_view, make_shell_command,
) -> None:
    # The background Bash process must not hide what main is doing now: the
    # activity column carries the current tool call, while cpu/mem/time still
    # reflect the owned process.
    activity = MainActivity(
        first_ts=NOW - 300, kind='tool_use', since=NOW - 1, mtime=NOW - 1,
        activity=('tool_use', tool, tool_input),
    )
    cmds = (make_shell_command('cargo build', elapsed=95, cpu=12.0, rss_kb=100 * 1024),)
    row = _agent_line(_lines(build_view([], cmds, activity=activity), 160, renderer), 'main')
    assert shown in row
    assert 'Bash[' not in row
    assert '12%' in row and '100M' in row and '1:35' in row


def test_main_current_bash_call_shows_the_live_child_command(
    monkeypatch: pytest.MonkeyPatch,
    renderer, build_view, make_shell_command,
) -> None:
    activity = MainActivity(
        first_ts=NOW - 300, kind='tool_use', since=NOW - 1, mtime=NOW - 1,
        activity=('tool_use', 'Bash', {'command': 'cargo build'}),
    )
    cmd = make_shell_command(
        'cargo build', background=False, elapsed=95, cpu=12.0, rss_kb=6 * 1024,
        live_command='rustc --crate-name yas',
    )
    row = _agent_line(_lines(build_view([], (cmd,), activity=activity), 160, renderer), 'main')
    assert 'Bash[rustc --crate-name yas]' in row
    assert 'cargo build' not in row


def test_main_thinking_is_not_masked_by_an_owned_background_bash_process(
    monkeypatch: pytest.MonkeyPatch,
    renderer, build_view, make_shell_command,
) -> None:
    activity = MainActivity(
        first_ts=NOW - 300, kind='thinking', since=NOW - 12, mtime=NOW - 1,
        activity=('thinking', '', {}),
    )
    cmds = (make_shell_command('cargo build', elapsed=95, cpu=12.0, rss_kb=100 * 1024),)
    row = _agent_line(_lines(build_view([], cmds, activity=activity), 160, renderer), 'main')
    assert '✻ Thinking…' in row
    assert 'Bash[' not in row
    # The owned process still drives the resource columns (and their timers).
    assert '12%' in row and '100M' in row and '1:35' in row


def test_labels_mark_the_agent_and_resource_columns(monkeypatch: pytest.MonkeyPatch, renderer, build_view, make_sub, make_shell_command) -> None:
    sub = make_sub('worker-a', commands=(('cargo build', 95),))
    sub.last_activity = ('tool_use', 'Bash', {'command': 'cargo build'})
    view = build_view([sub], (make_shell_command('cargo build', elapsed=95),), labels=True)
    lines = _lines(view, 160, renderer)
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
