#!/usr/bin/env python3
"""CPU profiling harness for the statusline renderer.

Profiles two scopes:
  * full   -- the whole main() path (stdin parse -> render -> stdout), as the
              real invocation runs it. Captures the per-module import cost too
              because the yas package is imported inside the profiled region.
  * render -- just render() called in a loop, to isolate steady-state render
              cost from one-shot import/startup overhead.

Usage:
    python3 ops/profile_statusline.py full   < ops/session-info-example.json
    python3 ops/profile_statusline.py render < ops/session-info-example.json

Writes a .pstats dump next to this file and prints a sorted summary.
"""
from __future__ import annotations

import cProfile
import io
import json
import pstats
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'claude'))

OUT_DIR = HERE / 'profile-out'
OUT_DIR.mkdir(exist_ok=True)


def _print_stats(pr: cProfile.Profile, tag: str) -> None:
    dump = OUT_DIR / f'{tag}.pstats'
    pr.dump_stats(str(dump))
    for sort in ('cumulative', 'tottime'):
        buf = io.StringIO()
        st = pstats.Stats(pr, stream=buf)
        st.sort_stats(sort).print_stats(35)
        print(f'\n===== {tag} sorted by {sort} =====')
        print(buf.getvalue())
    print(f'[wrote {dump}]')


def profile_full(raw: str) -> None:
    """Profile the cold path: imports + a single render via the public API."""
    pr = cProfile.Profile()
    pr.enable()
    # Imported inside the profiled region so per-module import cost shows up.
    from yas.app import render
    from yas.constants import MIN_WIDTH
    info = json.loads(raw)
    pr.disable()  # exclude json of the raw fixture from the cold measure boundary
    pr.enable()
    render(info, 160)
    pr.disable()
    _print_stats(pr, 'full')


def profile_render(raw: str, n: int = 200) -> None:
    """Profile steady-state render cost over N iterations (imports excluded)."""
    from yas.app import render
    info = json.loads(raw)
    render(info, 160)  # warm caches/imports outside the profiled region
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(n):
        render(info, 160)
    pr.disable()
    _print_stats(pr, 'render')
    # wall-clock per render
    t0 = time.perf_counter()
    for _ in range(n):
        render(info, 160)
    dt = (time.perf_counter() - t0) / n * 1000
    print(f'\n[render-only wall clock: {dt:.3f} ms/call over {n} calls]')


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'full'
    data = sys.stdin.read()
    if mode == 'render':
        profile_render(data)
    else:
        profile_full(data)
