"""Running Bash-tool shell commands of the current Claude Code session.

Claude runs each Bash-tool command as `<shell> -c 'source …/shell-snapshots/
snapshot-….sh … && eval '<cmd>' < /dev/null && pwd -P >| /tmp/claude-…-cwd'`
directly under the claude process. This module finds those processes, sums
cpu and memory over each subtree, and labels them background or foreground.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from yas.constants import _sanitize, shell_cpu_cache_path
from yas.info import bash_inflight
from yas.info.parsecache import fold_file

if TYPE_CHECKING:
    from yas.info.parsecache import TranscriptCache

FIXTURE_ENV = 'YAS_SHELL_COMMANDS_FIXTURE'
CLAUDE_NAME = 'claude'
SHELL_NAMES = ('bash', 'zsh', 'sh')
PID_REUSE_TOLERANCE_S = 3.0
MAX_BG_COMMANDS = 200
MAX_WALK = 64
OWNER_TIE_S = 1.0  # two owners this close in start-time distance are indistinguishable

# Anchored at the end: heredoc commands have no `< /dev/null` before `&& pwd -P`,
# and the command body may itself contain `< /dev/null` or `&& pwd -P`.
_EVAL_RE = re.compile(
    r'shell-snapshots/snapshot-.*?&&\s*eval\s+(?P<cmd>.*?)(?:\s*<\s*/dev/null)?\s*&&\s*pwd\s+-P\s*>\|\s*\S+\s*$',
    re.DOTALL,
)


@dataclass(frozen=True)
class ProcEntry:
    pid:       int
    ppid:      int
    rss_kb:    int
    cpu_s:     float
    elapsed_s: float
    argv:      str


@dataclass(frozen=True)
class ShellCommand:
    pid:         int
    command:     str
    background:  bool
    elapsed_s:   float
    cpu_percent: float | None
    rss_kb:      int


@dataclass(frozen=True)
class AgentUsage:
    'CPU, memory and longest elapsed time summed over one subagent\'s processes.'
    cpu_percent: float | None
    rss_kb:      int
    elapsed_s:   float

    @classmethod
    def of(cls, commands: tuple[ShellCommand, ...]) -> AgentUsage:
        cpus = [c.cpu_percent for c in commands if c.cpu_percent is not None]
        return cls(
            cpu_percent = sum(cpus) if cpus else None,
            rss_kb      = sum(c.rss_kb for c in commands),
            elapsed_s   = max(c.elapsed_s for c in commands),
        )


@dataclass(frozen=True)
class RunningShellCommands:
    commands: tuple[ShellCommand, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.commands)

    @property
    def count(self) -> int:
        return len(self.commands)

    @property
    def longest_elapsed_s(self) -> float:
        return max((c.elapsed_s for c in self.commands), default=0.0)

    @property
    def total_cpu_percent(self) -> float | None:
        vals = [c.cpu_percent for c in self.commands if c.cpu_percent is not None]
        return sum(vals) if vals else None

    @property
    def total_rss_kb(self) -> int:
        return sum(c.rss_kb for c in self.commands)

    @classmethod
    def from_session(
        cls,
        session_id: str,
        transcript_path: str | None,
        cfg: Any,
        now: float | None = None,
        table: list[ProcEntry] | None = None,
        self_pid: int | None = None,
        cache: TranscriptCache | None = None,
    ) -> RunningShellCommands:
        try:
            return cls._gather(session_id, transcript_path, cfg, now, table, self_pid, cache)
        except Exception:
            return cls()

    @classmethod
    def _gather(
        cls,
        session_id: str,
        transcript_path: str | None,
        cfg: Any,
        now: float | None,
        table: list[ProcEntry] | None,
        self_pid: int | None,
        cache: TranscriptCache | None = None,
    ) -> RunningShellCommands:
        now = time.time() if now is None else now
        if table is None:
            table = read_process_table()
        if self_pid is None:
            self_pid = fixture_self_pid() or os.getpid()

        by_pid = {e.pid: e for e in table}
        kids: dict[int, list[int]] = {}
        for e in table:
            kids.setdefault(e.ppid, []).append(e.pid)

        claude_pid = find_claude_pid(by_pid, self_pid)
        if claude_pid is None:
            return cls()

        found: list[tuple[ProcEntry, str, list[ProcEntry]]] = []
        for pid in kids.get(claude_pid, ()):
            entry = by_pid[pid]
            cmd = extract_command(entry.argv)
            if cmd is None:
                continue
            tree = subtree(pid, by_pid, kids)
            if any(t.pid == self_pid for t in tree):
                continue
            found.append((entry, cmd, tree))
        if not found:
            return cls()

        mode = cfg.cpu.mode
        cpus = cpu_percents(
            [(e, sum(t.cpu_s for t in tree)) for e, _, tree in found],
            mode, session_id, now,
        )
        bg = background_commands(transcript_path, cache)
        out = []
        for (entry, cmd, tree), cpu in zip(found, cpus):
            out.append(ShellCommand(
                pid=entry.pid,
                command=_sanitize(' '.join(cmd.split())),
                background=cmd.strip() in bg,
                elapsed_s=entry.elapsed_s,
                cpu_percent=cpu,
                rss_kb=sum(t.rss_kb for t in tree),
            ))
        return cls(commands=tuple(out))


def subtree(root: int, by_pid: dict[int, ProcEntry], kids: dict[int, list[int]]) -> list[ProcEntry]:
    out, stack, seen = [], [root], set()
    while stack:
        pid = stack.pop()
        if pid in seen or pid not in by_pid:
            continue
        seen.add(pid)
        out.append(by_pid[pid])
        stack.extend(kids.get(pid, ()))
    return out


def _basename(argv: str) -> str:
    first = argv.split(' ', 1)[0] if argv else ''
    return os.path.basename(first)


def find_claude_pid(by_pid: dict[int, ProcEntry], self_pid: int) -> int | None:
    """Nearest ancestor of self_pid whose command basename is `claude`."""
    me = by_pid.get(self_pid)
    pid = me.ppid if me is not None else os.getppid()
    for _ in range(MAX_WALK):
        entry = by_pid.get(pid)
        if entry is None:
            return None
        if _basename(entry.argv) == CLAUDE_NAME:
            return pid
        pid = entry.ppid
    return None


_LEADING_CD_RE = re.compile(
    r"""\s*cd(?:\s+(?:"[^"]*"|'[^']*'|[^\s;&]+))?\s*(?:&&|;|\n)""",
)


_BARE_CD_RE = re.compile(r"""cd(?:\s+(?:"[^"]*"|'[^']*'|[^\s;&]+))?""")


def strip_leading_cd(command: str) -> str:
    'Display form of `command` without leading `cd <path>` segments; unchanged when nothing else remains.'
    rest = command
    while m := _LEADING_CD_RE.match(rest):
        rest = rest[m.end():]
    rest = rest.strip()
    return command if not rest or _BARE_CD_RE.fullmatch(rest) else rest


def unquote_eval(arg: str) -> str:
    arg = arg.strip()
    if len(arg) >= 2 and arg[0] == arg[-1] == "'":
        arg = arg[1:-1]
    elif len(arg) >= 2 and arg[0] == arg[-1] == '"':
        arg = arg[1:-1].replace('\\"', '"')
    return arg.replace("'\"'\"'", "'").replace("'\\''", "'")


def extract_command(argv: str) -> str | None:
    """The user command from a Claude Bash-tool wrapper argv, else None."""
    if _basename(argv) not in SHELL_NAMES or ' -c ' not in argv:
        return None
    m = _EVAL_RE.search(argv)
    if m is None:
        return None
    return unquote_eval(m.group('cmd'))


# ---- process table -------------------------------------------------------

def fixture_self_pid() -> int | None:
    path = os.environ.get(FIXTURE_ENV)
    if not path:
        return None
    try:
        return int(json.loads(Path(path).read_text()).get('self_pid'))
    except (OSError, ValueError, TypeError):
        return None


def read_process_table() -> list[ProcEntry]:
    path = os.environ.get(FIXTURE_ENV)
    if path:
        data = json.loads(Path(path).read_text())
        return [ProcEntry(**d) for d in data.get('processes', [])]
    if sys.platform.startswith('linux'):
        return read_proc_table()
    return read_ps_table()


def parse_proc_stat(text: str) -> tuple[int, int, int, int]:
    """(ppid, cpu_ticks, start_ticks, rss_pages) from /proc/<pid>/stat text."""
    rest = text[text.rindex(')') + 1:].split()
    return int(rest[1]), int(rest[11]) + int(rest[12]), int(rest[19]), int(rest[21])


def read_proc_table(
    root: str = '/proc',
    now: float | None = None,
    clk_tck: int | None = None,
    page_kb: int | None = None,
) -> list[ProcEntry]:
    now = time.time() if now is None else now
    clk = clk_tck or os.sysconf('SC_CLK_TCK')
    page = page_kb or os.sysconf('SC_PAGE_SIZE') // 1024
    btime = 0.0
    with open(f'{root}/stat') as f:
        for line in f:
            if line.startswith('btime '):
                btime = float(line.split()[1])
                break
    out = []
    for name in os.listdir(root):
        if not name.isdigit():
            continue
        try:
            with open(f'{root}/{name}/stat') as f:
                ppid, cpu, start, rss = parse_proc_stat(f.read())
            with open(f'{root}/{name}/cmdline', 'rb') as f:
                raw = f.read()
        except (OSError, ValueError, IndexError):
            continue
        argv = raw.replace(b'\0', b' ').decode('utf-8', 'replace').strip()
        out.append(ProcEntry(
            pid=int(name), ppid=ppid, rss_kb=rss * page, cpu_s=cpu / clk,
            elapsed_s=max(0.0, now - (btime + start / clk)), argv=argv,
        ))
    return out


def parse_ps_time(s: str) -> float:
    """Seconds from `[[dd-]hh:]mm:ss[.xx]`."""
    days = 0
    if '-' in s:
        d, s = s.split('-', 1)
        days = int(d)
    total = 0.0
    for part in s.split(':'):
        total = total * 60 + float(part)
    return days * 86400 + total


def parse_ps_output(text: str) -> list[ProcEntry]:
    out = []
    for line in text.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 5:
            continue
        try:
            out.append(ProcEntry(
                pid=int(parts[0]), ppid=int(parts[1]), rss_kb=int(parts[2]),
                cpu_s=parse_ps_time(parts[3]), elapsed_s=parse_ps_time(parts[4]),
                argv=parts[5] if len(parts) > 5 else '',
            ))
        except ValueError:
            continue
    return out


def read_ps_table() -> list[ProcEntry]:
    res = subprocess.run(
        ['ps', '-A', '-o', 'pid=,ppid=,rss=,time=,etime=,command='],
        capture_output=True, text=True, timeout=2, check=True,
    )
    return parse_ps_output(res.stdout)


# ---- cpu -----------------------------------------------------------------

def cpu_percents(
    items: list[tuple[ProcEntry, float]],
    mode: str,
    session_id: str,
    now: float,
) -> list[float | None]:
    if mode != 'current':
        return [cpu / e.elapsed_s * 100 if e.elapsed_s > 0 else None for e, cpu in items]

    path = shell_cpu_cache_path(session_id)
    try:
        prev = json.loads(path.read_text())
        if not isinstance(prev, dict):
            prev = {}
    except (OSError, ValueError):
        prev = {}

    out: list[float | None] = []
    fresh: dict[str, dict[str, float]] = {}
    for e, cpu in items:
        start = now - e.elapsed_s
        fresh[str(e.pid)] = {'start': start, 'cpu': cpu, 't': now}
        old = prev.get(str(e.pid))
        pct = None
        try:
            if old and abs(old['start'] - start) <= PID_REUSE_TOLERANCE_S and now > old['t']:
                pct = max(0.0, (cpu - old['cpu']) / (now - old['t']) * 100)
        except (KeyError, TypeError):
            pct = None
        out.append(pct)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(fresh))
        os.replace(tmp, path)
    except OSError:
        pass
    return out


# ---- background detection -----------------------------------------------

def _bg_init() -> dict[str, Any]:
    return {'cmds': []}


def _bg_fold(state: dict[str, Any], lines: list[bytes]) -> dict[str, Any]:
    cmds = state.setdefault('cmds', [])
    for raw in lines:
        if b'run_in_background' not in raw:
            continue
        try:
            d = json.loads(raw.decode('utf-8', 'ignore'))
        except ValueError:
            continue
        content = (d.get('message') or {}).get('content')
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict) or c.get('type') != 'tool_use' or c.get('name') != 'Bash':
                continue
            inp = c.get('input') or {}
            if inp.get('run_in_background') is True and isinstance(inp.get('command'), str):
                cmds.append(inp['command'].strip())
    del cmds[:-MAX_BG_COMMANDS]
    return state


def background_commands(transcript_path: str | None, cache: TranscriptCache | None = None) -> set[str]:
    if not transcript_path:
        return set()
    try:
        st = os.stat(transcript_path) if cache is not None else None
        return set(fold_file(cache, transcript_path, st, 'shellbg', '', _bg_init, _bg_fold).get('cmds', []))
    except Exception:
        return set()


# ---- subagent ownership ---------------------------------------------------

def _flight_init() -> dict[str, Any]:
    return {'calls': {}}


def _flight_fold(state: dict[str, Any], lines: list[bytes]) -> dict[str, Any]:
    calls = state.setdefault('calls', {})
    for raw in lines:
        if b'"Bash"' in raw or b'tool_use_id' in raw:
            bash_inflight.fold_line(calls, raw.decode('utf-8', 'ignore'))
    return state


def main_inflight(transcript_path: str | None, cache: TranscriptCache | None = None) -> tuple[tuple[str, float], ...]:
    'In-flight `(command, timestamp)` Bash calls of the main transcript.'
    if not transcript_path:
        return ()
    try:
        st = os.stat(transcript_path) if cache is not None else None
        state = fold_file(cache, transcript_path, st, 'shellflight', '', _flight_init, _flight_fold)
        return bash_inflight.inflight(state.get('calls', {}))
    except Exception:
        return ()


def split_by_owner(
    commands: tuple[ShellCommand, ...],
    owners: dict[str, tuple[tuple[str, float], ...]],
    main_calls: Callable[[], tuple[tuple[str, float], ...]],
    now: float,
) -> tuple[tuple[ShellCommand, ...], dict[str, tuple[ShellCommand, ...]]]:
    """Split `commands` into main-thread ones and ones owned by a subagent.

    A command is owned when its text equals an in-flight Bash call of exactly
    one subagent, judged by the call whose timestamp is closest to the process
    start. The main thread competes through `main_calls` (read only when a
    subagent text matches). A tie between different owners leaves the command
    with the main thread; each in-flight call is claimed by one process.
    """
    pool: dict[str, list[tuple[str | None, float]]] = {}
    for owner, calls in owners.items():
        for text, ts in calls:
            pool.setdefault(text, []).append((owner, ts))
    if not any(c.command in pool for c in commands):
        return commands, {}
    for text, ts in main_calls():
        if text in pool:
            pool[text].append((None, ts))

    owned: dict[int, str] = {}
    for i in sorted(range(len(commands)), key=lambda i: -commands[i].elapsed_s):
        cmd = commands[i]
        start = now - cmd.elapsed_s
        ranked = sorted(pool.get(cmd.command, ()), key=lambda c: abs(c[1] - start))
        if not ranked:
            continue
        best = ranked[0]
        rival = next((c for c in ranked[1:] if c[0] != best[0]), None)
        if rival is not None and abs(rival[1] - start) - abs(best[1] - start) < OWNER_TIE_S:
            continue
        pool[cmd.command].remove(best)
        if best[0] is not None:
            owned[i] = best[0]
    mine = tuple(c for i, c in enumerate(commands) if i not in owned)
    theirs: dict[str, list[ShellCommand]] = {}
    for i, owner in sorted(owned.items()):
        theirs.setdefault(owner, []).append(commands[i])
    return mine, {o: tuple(cs) for o, cs in theirs.items()}
