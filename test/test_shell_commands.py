from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yas.info import shell_commands as sc
from yas.info.shell_commands import ProcEntry, RunningShellCommands, strip_leading_cd

NOW = 10_000.0
CFG_AVG = SimpleNamespace(cpu=SimpleNamespace(mode='average'))
CFG_CUR = SimpleNamespace(cpu=SimpleNamespace(mode='current'))


def wrapper(cmd: str, shell: str = '/bin/bash') -> str:
    q = cmd.replace("'", "'\"'\"'")
    return (
        f"{shell} -c source /home/u/.claude/shell-snapshots/snapshot-bash-1-abc.sh 2>/dev/null "
        f"|| true && shopt -u extglob && eval '{q}' < /dev/null && pwd -P >| /tmp/claude-1f2-cwd"
    )


def pe(pid, ppid, argv='x', cpu=0.0, elapsed=100.0, rss=10):
    return ProcEntry(pid=pid, ppid=ppid, rss_kb=rss, cpu_s=cpu, elapsed_s=elapsed, argv=argv)


def base_table(*extra):
    return [
        pe(1, 0, 'init'),
        pe(10, 1, '/usr/bin/claude --flag'),
        pe(20, 10, 'node statusline'),
        pe(30, 20, 'python statusline.py'),
        *extra,
    ]


def run(table, cfg=CFG_AVG, transcript=None, session='s1'):
    return RunningShellCommands.from_session(
        session, transcript, cfg, now=NOW, table=table, self_pid=30,
    )


@pytest.mark.parametrize('cmd', [
    'sleep 5',
    "echo 'hi there'",
    'echo "a" && ls',
])
def test_extract_command_roundtrips_quoting(cmd):
    assert sc.extract_command(wrapper(cmd)) == cmd


def test_extract_command_alt_quote_and_zsh():
    argv = wrapper('x', '/bin/zsh').replace("'x'", "'it'\\''s'")
    assert sc.extract_command(argv) == "it's"


@pytest.mark.parametrize('argv', [
    'bash -c ls',
    '/bin/bash -c echo hi',
    'python -c "eval foo"',
    '',
])
def test_extract_command_rejects_non_wrapper(argv):
    assert sc.extract_command(argv) is None


def test_claude_walk_skips_wrapping_shell():
    table = {e.pid: e for e in [
        pe(1, 0, 'init'), pe(10, 1, 'claude'), pe(15, 10, 'bash -l'), pe(30, 15, 'py'),
    ]}
    assert sc.find_claude_pid(table, 30) == 10


def test_claude_walk_missing():
    table = {e.pid: e for e in [pe(1, 0, 'init'), pe(30, 1, 'py')]}
    assert sc.find_claude_pid(table, 30) is None
    assert run([pe(1, 0, 'init'), pe(30, 1, 'py')]).count == 0


def test_running_command_found():
    res = run(base_table(pe(40, 10, wrapper('sleep 9'), cpu=10, elapsed=100)))
    assert res.count == 1
    assert res.commands[0].command == 'sleep 9'
    assert res.commands[0].background is False


def test_self_tree_excluded():
    own = pe(25, 10, wrapper('statusline-own'))
    table = [pe(1, 0, 'init'), pe(10, 1, 'claude'), own, pe(30, 25, 'py')]
    assert run(table).count == 0


def test_tree_aggregation_and_average_cpu():
    table = base_table(
        pe(40, 10, wrapper('make'), cpu=10, elapsed=100, rss=100),
        pe(41, 40, 'make', cpu=20, elapsed=90, rss=200),
        pe(42, 41, 'cc', cpu=20, elapsed=80, rss=300),
    )
    cmd = run(table).commands[0]
    assert cmd.rss_kb == 600
    assert cmd.cpu_percent == pytest.approx(50.0)
    assert cmd.elapsed_s == 100


def test_totals():
    table = base_table(
        pe(40, 10, wrapper('a'), cpu=10, elapsed=100, rss=1),
        pe(41, 10, wrapper('b'), cpu=30, elapsed=200, rss=2),
    )
    res = run(table)
    assert res.total_rss_kb == 3
    assert res.total_cpu_percent == pytest.approx(25.0)
    assert res.longest_elapsed_s == 200


def test_current_first_none_then_value_and_pid_reuse(tmp_home):
    def table(cpu, elapsed, pid=40):
        return base_table(pe(pid, 10, wrapper('w'), cpu=cpu, elapsed=elapsed))

    def go(t, now):
        return RunningShellCommands.from_session(
            's1', None, CFG_CUR, now=now, table=t, self_pid=30,
        ).commands[0].cpu_percent

    assert go(table(10, 100), NOW) is None
    assert go(table(15, 110), NOW + 10) == pytest.approx(50.0)
    # same pid, different start time: reused pid is ignored
    assert go(table(1, 5), NOW + 20) is None


def test_ps_time_parsing():
    assert sc.parse_ps_time('01:02') == 62
    assert sc.parse_ps_time('01:02:03') == 3723
    assert sc.parse_ps_time('2-01:00:00') == 2 * 86400 + 3600
    assert sc.parse_ps_time('00:01.50') == pytest.approx(1.5)


def test_parse_ps_output():
    text = '  10   1  2048 00:01.50 01:00 /usr/bin/claude --x\n  bad line\n'
    (e,) = sc.parse_ps_output(text)
    assert (e.pid, e.ppid, e.rss_kb, e.cpu_s, e.elapsed_s) == (10, 1, 2048, 1.5, 60)
    assert e.argv == '/usr/bin/claude --x'


def test_parse_proc_stat_with_parens_in_comm():
    rest = ['S', '7'] + ['0'] * 9 + ['100', '50'] + ['0'] * 6 + ['900', '0', '33']
    text = '42 (a) b (c d) ' + ' '.join(rest)
    assert sc.parse_proc_stat(text) == (7, 150, 900, 33)


def test_read_proc_table_fake_root(tmp_path):
    (tmp_path / 'stat').write_text('cpu 1\nbtime 1000\n')
    d = tmp_path / '42'
    d.mkdir()
    rest = ['S', '7'] + ['0'] * 9 + ['100', '50'] + ['0'] * 6 + ['500', '0', '3']
    (d / 'stat').write_text('42 (we ird) ' + ' '.join(rest))
    (d / 'cmdline').write_bytes(b'bash\0-c\0ls\0')
    (tmp_path / '99').mkdir()  # vanished: no stat
    (tmp_path / 'self').mkdir()
    (e,) = sc.read_proc_table(str(tmp_path), now=1100.0, clk_tck=100, page_kb=4)
    assert (e.pid, e.ppid, e.rss_kb, e.cpu_s, e.elapsed_s) == (42, 7, 12, 1.5, 95.0)
    assert e.argv == 'bash -c ls'


def test_transcript_background_match(tmp_path):
    tp = tmp_path / 't.jsonl'
    lines = [
        {'message': {'content': [{'type': 'tool_use', 'name': 'Bash',
                                  'input': {'command': 'sleep 9', 'run_in_background': True}}]}},
        {'message': {'content': [{'type': 'tool_use', 'name': 'Bash',
                                  'input': {'command': 'ls'}}]}},
    ]
    tp.write_text('\n'.join(json.dumps(x) for x in lines) + '\n')
    table = base_table(
        pe(40, 10, wrapper('sleep 9'), cpu=1),
        pe(41, 10, wrapper('ls'), cpu=1),
    )
    res = run(table, transcript=str(tp))
    assert {c.command: c.background for c in res.commands} == {'sleep 9': True, 'ls': False}


def test_missing_transcript_is_foreground():
    res = run(base_table(pe(40, 10, wrapper('x'))), transcript='/nonexistent')
    assert res.commands[0].background is False


def test_failure_gives_empty():
    assert not RunningShellCommands.from_session('s', None, CFG_AVG, table=[object()])


def test_fixture_env(tmp_path, monkeypatch):
    f = tmp_path / 'fx.json'
    f.write_text(json.dumps({'self_pid': 30, 'processes': [
        {'pid': 10, 'ppid': 1, 'rss_kb': 1, 'cpu_s': 0, 'elapsed_s': 5, 'argv': 'claude'},
        {'pid': 30, 'ppid': 10, 'rss_kb': 1, 'cpu_s': 0, 'elapsed_s': 5, 'argv': 'py'},
        {'pid': 40, 'ppid': 10, 'rss_kb': 1, 'cpu_s': 1, 'elapsed_s': 5, 'argv': wrapper('demo')},
    ]}))
    monkeypatch.setenv(sc.FIXTURE_ENV, str(f))
    res = RunningShellCommands.from_session('s', None, CFG_AVG)
    assert [c.command for c in res.commands] == ['demo']


FIXTURES = Path(__file__).parent / 'fixtures' / 'shell_commands'


def fixture_argv(name: str) -> str:
    raw = (FIXTURES / f'{name}.cmdline').read_bytes()
    return raw.replace(b'\0', b' ').decode().strip()


def test_extract_sleep_background_fixture():
    assert sc.extract_command(fixture_argv('sleep_bg')) == 'sleep 600; echo done'


def test_extract_heredoc_cat_fixture():
    cmd = sc.extract_command(fixture_argv('heredoc_cat'))
    assert cmd.startswith('cat > .scratch/feat-shell-commands-section/edit.py 2>/dev/null; rm -f ')
    assert cmd.endswith(argv_tail('heredoc_cat'))
    assert "'\"'\"'" not in cmd
    assert '/tmp/claude-' not in cmd


def test_extract_cd_multiline_fixture():
    cmd = sc.extract_command(fixture_argv('cd_multiline'))
    assert cmd.startswith("cd /home/freman/dev/yet-another-statusline\ncat >> test/test_config.py <<'EOF'")
    assert cmd.endswith(argv_tail('cd_multiline'))
    assert '/tmp/claude-' not in cmd


def test_extract_python_stdin_fixture():
    cmd = sc.extract_command(fixture_argv('python_stdin'))
    assert cmd.startswith("python - 2>/dev/null; uv run python - <<'E'\np='claude/yas/info/__init__.py'")
    assert cmd.endswith("def shell_commands_list\" -A75 claude/yas/renderer.py")
    assert '/tmp/claude-' not in cmd


def argv_tail(name: str) -> str:
    'Last 30 chars of the command, taken from the argv by structure.'
    argv = fixture_argv(name)
    body = argv[argv.index('&& eval \'') + len('&& eval \''):argv.rindex("' && pwd -P")]
    return body.replace("'\"'\"'", "'")[-30:]


def test_extract_ignores_dev_null_and_pwd_inside_command():
    cmd = 'cat < /dev/null && pwd -P >| /tmp/x; echo hi'
    assert sc.extract_command(wrapper(cmd)) == cmd


def test_extract_heredoc_wrapper_without_dev_null():
    cmd = "cat <<'EOF'\nx\nEOF"
    q = cmd.replace("'", "'\"'\"'")
    argv = (
        '/bin/bash -c source /h/.claude/shell-snapshots/snapshot-bash-1-a.sh 2>/dev/null '
        f"|| true && eval '{q}' && pwd -P >| /tmp/claude-1f2-cwd"
    )
    assert sc.extract_command(argv) == cmd


def test_background_scan_resumes_from_last_offset(tmp_path, tmp_home, monkeypatch):
    from yas.info import parsecache

    tp = tmp_path / 't.jsonl'

    def line(cmd):
        return json.dumps({'message': {'content': [{'type': 'tool_use', 'name': 'Bash',
                                                    'input': {'command': cmd, 'run_in_background': True}}]}}) + '\n'

    tp.write_text(line('sleep 1'))
    cache = parsecache.TranscriptCache('s1')
    assert sc.background_commands(str(tp), cache) == {'sleep 1'}

    with tp.open('a') as f:
        f.write(line('sleep 2'))
    seen = []
    real = sc._bg_fold
    monkeypatch.setattr(sc, '_bg_fold', lambda st, lines: (seen.extend(lines), real(st, lines))[1])
    assert sc.background_commands(str(tp), cache) == {'sleep 1', 'sleep 2'}
    assert len(seen) == 1


@pytest.mark.parametrize('command, shown', [
    ('cd /a && cd b; make test', 'make test'),
    ('cd "/a b" && x', 'x'),
    ("cd '/a b'; x", 'x'),
    ('  cd /a  &&   x  ', 'x'),
    ('cd /a\nmake', 'make'),
    ('cd /a && cd /b', 'cd /a && cd /b'),
    ('cd', 'cd'),
    ('cd /a', 'cd /a'),
    ('make && cd x', 'make && cd x'),
    ('cdk deploy', 'cdk deploy'),
    (
        "cd /home/freman/dev/audiovis/.scratch/feat-section-taxonomy/reanalyse/w2; jq -c '.[]' results.json; ./run.sh | tail -3",
        "jq -c '.[]' results.json; ./run.sh | tail -3",
    ),
])
def test_strip_leading_cd_for_display(command: str, shown: str) -> None:
    assert strip_leading_cd(command) == shown
