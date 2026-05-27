#!/usr/bin/env python3
'Benchmark the statusline command: current tree (PR) vs a base git ref (default main).'

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

BOLD   = '\033[1m'
DIM    = '\033[2m'
YELLOW = '\033[33m'
RESET  = '\033[0m'

REPO_ROOT  = Path(__file__).resolve().parent.parent
STATUSLINE = Path('claude/statusline_command.py')
INPUT_JSON = REPO_ROOT / 'claude' / 'statusline' / 'session-info-example.json'

HYPERFINE_HINT = (
    'hyperfine not found, using the Python fallback timer.\n'
    'For warmup/outlier handling and a nicer report, install it:\n'
    '  apt install hyperfine    # debian/ubuntu\n'
    '  brew install hyperfine   # macOS\n'
    '  cargo install hyperfine  # any platform with rust'
)


def git(*args: str, cwd: Path = REPO_ROOT) -> str:
    'Run a git command in `cwd` and return its stripped stdout.'
    result = subprocess.run(
        ['git', *args],
        cwd            = cwd,
        capture_output = True,
        text           = True,
        check          = True,
    )
    return result.stdout.strip()


@contextlib.contextmanager
def base_worktree(ref: str) -> Iterator[Path]:
    'Check `ref` out into a throwaway detached worktree, removed on exit.'
    tmp  = Path(tempfile.mkdtemp(prefix='yas-bench-'))
    tree = tmp / 'tree'
    git('worktree', 'add', '--quiet', '--detach', str(tree), ref)
    try:
        yield tree
    finally:
        git('worktree', 'remove', '--force', str(tree))
        shutil.rmtree(tmp, ignore_errors=True)


@contextlib.contextmanager
def realistic_scenario(n_lines: int) -> Iterator[tuple[bytes, dict[str, str]]]:
    '''Yield (stdin_bytes, env) for a realistic render: a temp CLAUDE_CONFIG_DIR
    holding an `n_lines` transcript under projects/ (so the PR's incremental
    tailing engages) plus a session JSON pointing at it. The base ref ignores
    the dir and just scans transcript_path, so both are timed on the same
    transcript. Warmup runs prime the PR's incremental state, so the measured
    PR runs reflect steady-state (tail-only) cost.'''
    tmp = Path(tempfile.mkdtemp(prefix='yas-bench-real-'))
    try:
        sid  = 'bench-session'
        proj = tmp / 'projects' / 'bench-slug'
        proj.mkdir(parents=True)
        transcript = proj / f'{sid}.jsonl'
        rows = [
            json.dumps({'type': 'assistant', 'message': {
                'id': f'm{i}', 'role': 'assistant',
                'usage': {'input_tokens': 100, 'cache_creation_input_tokens': 0,
                          'cache_read_input_tokens': 50, 'output_tokens': 20}}})
            for i in range(n_lines)
        ]
        transcript.write_text('\n'.join(rows) + '\n')
        info = json.loads(INPUT_JSON.read_text())
        info['session_id'] = sid
        info['transcript_path'] = str(transcript)
        env = dict(os.environ)
        env['CLAUDE_CONFIG_DIR'] = str(tmp)
        print(f'{DIM}realistic transcript: {n_lines} lines, {transcript.stat().st_size} bytes{RESET}', file=sys.stderr)
        yield json.dumps(info).encode(), env
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def shell_invocation(script: Path) -> str:
    'A `python3 <script> < <input>` string, quoted so spaces in paths survive.'
    return f'python3 {shlex.quote(str(script))} < {shlex.quote(str(INPUT_JSON))}'


def run_hyperfine(base_script: Path, head_script: Path, base_label: str, runs: int, warmup: int) -> int:
    'Delegate to hyperfine and echo its paste-ready markdown table.'
    markdown = Path(tempfile.mkstemp(prefix='yas-bench-', suffix='.md')[1])
    try:
        subprocess.run(
            [
                'hyperfine',
                '--warmup', str(warmup),
                '--runs',   str(runs),
                '--command-name', base_label, shell_invocation(base_script),
                '--command-name', 'PR',       shell_invocation(head_script),
                '--export-markdown', str(markdown),
            ],
            check = True,
        )
        print(f'\n{BOLD}Paste-ready:{RESET}\n')
        print(markdown.read_text().strip())
        return 0
    finally:
        markdown.unlink(missing_ok=True)


@dataclass
class Stats:
    'Summary timings for one command, in milliseconds.'

    mean_ms:  float
    stdev_ms: float
    min_ms:   float

    @classmethod
    def measure(cls, script: Path, runs: int, warmup: int,
                input_data: bytes | None = None, env: dict[str, str] | None = None) -> Stats:
        'Time `runs` subprocess invocations after `warmup` throwaway runs.'
        from time import perf_counter

        data = input_data if input_data is not None else INPUT_JSON.read_bytes()
        argv = ['python3', str(script)]
        for _ in range(warmup):
            subprocess.run(argv, input=data, capture_output=True, check=True, env=env)
        samples: list[float] = []
        for _ in range(runs):
            start = perf_counter()
            subprocess.run(argv, input=data, capture_output=True, check=True, env=env)
            samples.append((perf_counter() - start) * 1000)
        return cls(
            mean_ms  = statistics.mean(samples),
            stdev_ms = statistics.stdev(samples) if len(samples) > 1 else 0.0,
            min_ms   = min(samples),
        )


def comparison(base_label: str, base: Stats, head: Stats) -> str:
    'A one-line relative-speed verdict with propagated error, hyperfine-style.'
    faster, faster_label, slower, slower_label = (
        (head, 'PR', base, base_label)
        if head.mean_ms < base.mean_ms
        else (base, base_label, head, 'PR')
    )
    ratio = slower.mean_ms / faster.mean_ms
    rel   = ((slower.stdev_ms / slower.mean_ms) ** 2 + (faster.stdev_ms / faster.mean_ms) ** 2) ** 0.5
    return f'{BOLD}{slower_label} ran {ratio:.2f} ± {ratio * rel:.2f} times slower than {faster_label}{RESET}'


def run_python(base_script: Path, head_script: Path, base_label: str, runs: int, warmup: int,
               input_data: bytes | None = None, env: dict[str, str] | None = None) -> int:
    'Time both commands with the stdlib fallback and print a markdown table.'
    print(f'{DIM}timing {base_label}…{RESET}', file=sys.stderr)
    base = Stats.measure(base_script, runs, warmup, input_data, env)
    print(f'{DIM}timing PR…{RESET}', file=sys.stderr)
    head = Stats.measure(head_script, runs, warmup, input_data, env)
    rows = [
        '| Command | Mean [ms] | Min [ms] |',
        '|:--------|----------:|---------:|',
        f'| `{base_label}` | {base.mean_ms:.1f} ± {base.stdev_ms:.1f} | {base.min_ms:.1f} |',
        f'| `PR` | {head.mean_ms:.1f} ± {head.stdev_ms:.1f} | {head.min_ms:.1f} |',
    ]
    print(f'\n{BOLD}Paste-ready:{RESET}\n')
    print('\n'.join(rows))
    print(f'\n{comparison(base_label, base, head)}')
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',   default='main', help='git ref to compare against (default: main)')
    parser.add_argument('--timer',  choices=('auto', 'hyperfine', 'python'), default='auto',
                        help='timer to use; auto picks hyperfine when available (default: auto)')
    parser.add_argument('--runs',   type=int, default=50, help='measured runs per command (default: 50)')
    parser.add_argument('--warmup', type=int, default=3, help='warmup runs per command (default: 3)')
    parser.add_argument('--transcript-lines', type=int, default=0,
                        help='bench against a generated N-line transcript under a temp CLAUDE_CONFIG_DIR '
                             '(default: 0 = legacy 1.2KB fixture, which does not exercise transcript scanning)')
    return parser.parse_args()


def main() -> int:
    args: argparse.Namespace = parse_args()
    base:   str = args.base
    timer:  str = args.timer
    runs:   int = args.runs
    warmup: int = args.warmup

    if not INPUT_JSON.exists():
        print(f'input fixture missing: {INPUT_JSON}', file=sys.stderr)
        return 1

    tlines: int = args.transcript_lines
    use_hyperfine = timer == 'hyperfine' or (timer == 'auto' and shutil.which('hyperfine') is not None)
    if tlines > 0:
        use_hyperfine = False  # the realistic scenario needs a custom stdin + env; use the python timer
    if not use_hyperfine and timer != 'python' and tlines == 0:
        print(f'{YELLOW}{HYPERFINE_HINT}{RESET}\n', file=sys.stderr)

    try:
        with base_worktree(base) as tree:
            base_script = tree / STATUSLINE
            head_script = REPO_ROOT / STATUSLINE
            if use_hyperfine:
                return run_hyperfine(base_script, head_script, base, runs, warmup)
            if tlines > 0:
                with realistic_scenario(tlines) as (input_data, env):
                    return run_python(base_script, head_script, base, runs, warmup, input_data, env)
            return run_python(base_script, head_script, base, runs, warmup)
    except subprocess.CalledProcessError as exc:
        print(f'benchmark failed: {shlex.join(exc.cmd)} exited {exc.returncode}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
