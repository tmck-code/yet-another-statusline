#!/usr/bin/env python3
'Benchmark the statusline command: current tree (PR) vs a base git ref (default main).'

from __future__ import annotations

import argparse
import contextlib
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
INPUT_JSON = REPO_ROOT / 'ops' / 'session-info-example.json'

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
    def measure(cls, script: Path, runs: int, warmup: int) -> Stats:
        'Time `runs` subprocess invocations after `warmup` throwaway runs.'
        from time import perf_counter

        data = INPUT_JSON.read_bytes()
        argv = ['python3', str(script)]
        for _ in range(warmup):
            subprocess.run(argv, input=data, capture_output=True, check=True)
        samples: list[float] = []
        for _ in range(runs):
            start = perf_counter()
            subprocess.run(argv, input=data, capture_output=True, check=True)
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


def run_python(base_script: Path, head_script: Path, base_label: str, runs: int, warmup: int) -> int:
    'Time both commands with the stdlib fallback and print a markdown table.'
    print(f'{DIM}timing {base_label}…{RESET}', file=sys.stderr)
    base = Stats.measure(base_script, runs, warmup)
    print(f'{DIM}timing PR…{RESET}', file=sys.stderr)
    head = Stats.measure(head_script, runs, warmup)
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

    use_hyperfine = timer == 'hyperfine' or (timer == 'auto' and shutil.which('hyperfine') is not None)
    if not use_hyperfine and timer != 'python':
        print(f'{YELLOW}{HYPERFINE_HINT}{RESET}\n', file=sys.stderr)

    try:
        with base_worktree(base) as tree:
            base_script = tree / STATUSLINE
            head_script = REPO_ROOT / STATUSLINE
            if use_hyperfine:
                return run_hyperfine(base_script, head_script, base, runs, warmup)
            return run_python(base_script, head_script, base, runs, warmup)
    except subprocess.CalledProcessError as exc:
        print(f'benchmark failed: {shlex.join(exc.cmd)} exited {exc.returncode}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
