#!/usr/bin/env python3
'''Benchmark import time of JSON libraries vs the stdlib `json`.

Motivation: profiling (see ops/profile-out/FINDINGS.md) shows the statusline's
cost is dominated by import time, and on Python 3.15 `json` (~5 ms cumulative,
pulling `re`/`enum`/`json.*`) is one of the heaviest stdlib modules that loads
on every invocation. This measures whether a drop-in alternative imports faster.

Each candidate is imported in a *fresh* subprocess under `-X importtime`; we
parse the per-module microsecond breakdown. Two metrics, median over RUNS:

  * cold    -- total self-time the import adds over a bare `python -c pass`.
               (what it costs on an otherwise-empty interpreter)
  * marginal -- total self-time it adds over an interpreter that has ALREADY
               imported `re`. yas always loads `re` (constants.py:_ANSI_RE), so
               this is the real saving available in-context: stdlib `json`'s
               `re` pull is already paid for, an extension module's is not.

Usage:
    ops/.bench-venv/bin/python ops/bench_json_import.py
'''
from __future__ import annotations

import re
import statistics
import subprocess
import sys

RUNS = 31

# (label, import statement). msgspec's JSON codec lives in msgspec.json.
CANDIDATES = [
    ('json (stdlib)', 'import json'),
    ('orjson',        'import orjson'),
    ('ujson',         'import ujson'),
    ('rapidjson',     'import rapidjson'),
    ('simplejson',    'import simplejson'),
    ('msgspec.json',  'import msgspec.json'),
]

_LINE = re.compile(r'^import time:\s+(\d+) \|\s+\d+ \|\s+(.*)$')


def _self_times(stmt: str) -> dict[str, int]:
    '''Map module-name -> self microseconds for one -X importtime subprocess.'''
    proc = subprocess.run(
        [sys.executable, '-X', 'importtime', '-c', stmt],
        capture_output=True,
        text=True,
    )
    times: dict[str, int] = {}
    for line in proc.stderr.splitlines():
        m = _LINE.match(line)
        if m:
            times[m.group(2).strip()] = int(m.group(1))
    return times


def _added_self_us(stmt: str, baseline: str) -> int:
    '''Total self-us of modules `stmt` imports that `baseline` did not.'''
    base = set(_self_times(baseline))
    return sum(us for name, us in _self_times(stmt).items() if name not in base)


def _median_us(stmt: str, baseline: str) -> float:
    samples = [_added_self_us(stmt, baseline) for _ in range(RUNS)]
    return statistics.median(samples)


def main() -> None:
    print(f'interpreter: {sys.version.split()[0]}  ({sys.executable})')
    print(f'runs: {RUNS} (median reported)\n')

    rows = []
    for label, stmt in CANDIDATES:
        cold = _median_us(stmt, 'pass') / 1000
        marginal = _median_us(stmt, 'import re') / 1000
        # one extra run kept for the child-module breakdown
        pulled = sorted(
            (us, name) for name, us in _self_times(stmt).items()
            if name not in set(_self_times('pass'))
        )
        top = ', '.join(f'{name}' for _, name in pulled[-4:][::-1])
        rows.append((label, cold, marginal, top))

    w = max(len(r[0]) for r in rows)
    print(f'{"library":<{w}}  {"cold ms":>8}  {"marginal ms":>11}   top modules pulled')
    print('-' * (w + 60))
    for label, cold, marginal, top in rows:
        print(f'{label:<{w}}  {cold:>8.2f}  {marginal:>11.2f}   {top}')


if __name__ == '__main__':
    main()
