#!/usr/bin/env python3
"""Live multi-session token activity viewer."""

import os
import time
from pathlib import Path

HOME = Path(os.path.expanduser('~'))
LOG_PATH = HOME / '.claude' / 'statusline-token-rate.log'
WINDOW = 60.0
KEEP = 180.0
N_BUCKETS = 30
REFRESH = 2

RESET = '\033[0m'
CLR_GREY_DIM = '\033[38;5;244m'
CLR_GREY_DARK = '\033[38;5;238m'
BOLD = '\033[1m'
SPARK_CHARS = '▁▂▃▄▅▆▇█'

GRAD_STOPS = (
    (0.00, (40, 200, 80)),
    (0.50, (240, 220, 40)),
    (0.75, (240, 140, 30)),
    (1.00, (220, 40, 40)),
)


def gradient_color(t: float) -> str:
    t = max(0.0, min(1.0, t))
    for i in range(len(GRAD_STOPS) - 1):
        t0, c0 = GRAD_STOPS[i]
        t1, c1 = GRAD_STOPS[i + 1]
        if t <= t1:
            u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            r = int(c0[0] + (c1[0] - c0[0]) * u)
            g = int(c0[1] + (c1[1] - c0[1]) * u)
            b = int(c0[2] + (c1[2] - c0[2]) * u)
            return f'\033[38;2;{r};{g};{b}m'
    r, g, b = GRAD_STOPS[-1][1]
    return f'\033[38;2;{r};{g};{b}m'


def sparkline(history: list[int]) -> str:
    if not history:
        return ''
    max_val = max(history)
    parts = []
    for val in history:
        if val == 0 or max_val == 0:
            parts.append(f'{CLR_GREY_DARK}▁{RESET}')
        else:
            ratio = val / max_val
            idx = min(int(ratio * 7), 7)
            parts.append(f'{gradient_color(ratio)}{SPARK_CHARS[idx]}{RESET}')
    return ''.join(parts)


def fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f'{n/1_000_000:.1f}M'
    if n >= 1000:
        return f'{n/1000:.1f}K'
    return str(n)


def read_log(now: float) -> list[tuple[float, str, int, int]]:
    if not LOG_PATH.exists():
        return []
    rows = []
    for ln in LOG_PATH.read_text().splitlines():
        parts = ln.split()
        if len(parts) < 4:
            continue
        try:
            ts = float(parts[0])
            sid = parts[1]
            ti = int(parts[2])
            to = int(parts[3])
        except ValueError:
            continue
        if now - ts <= KEEP:
            rows.append((ts, sid, ti, to))
    return rows


def build_session_rows(now: float) -> list[tuple[str, list[int], int, bool]]:
    rows = read_log(now)
    sessions: dict[str, list[tuple[float, int, int]]] = {}
    for ts, sid, ti, to in rows:
        sessions.setdefault(sid, []).append((ts, ti, to))

    result = []
    bucket_size = WINDOW / N_BUCKETS
    start = now - WINDOW

    for sid, samples in sessions.items():
        samples.sort()
        latest_ts = samples[-1][0]
        is_idle = (now - latest_ts) > WINDOW

        active_samples = [(ts, ti, to) for ts, ti, to in samples if now - ts <= WINDOW]
        if len(active_samples) < 2:
            buckets = [0] * N_BUCKETS
            rate = 0
        else:
            buckets = [0] * N_BUCKETS
            for i in range(len(active_samples) - 1):
                ts0, ti0, to0 = active_samples[i]
                ts1, ti1, to1 = active_samples[i + 1]
                delta = max(0, (ti1 + to1) - (ti0 + to0))
                if delta == 0:
                    continue
                midpoint = (ts0 + ts1) / 2
                idx = int((midpoint - start) / bucket_size)
                idx = max(0, min(N_BUCKETS - 1, idx))
                buckets[idx] += delta
            rate = max(0, (active_samples[-1][1] + active_samples[-1][2]) - (active_samples[0][1] + active_samples[0][2]))

        result.append((sid, buckets, rate, is_idle))
    return result


def render(now: float) -> None:
    print('\033[2J\033[H', end='')
    print(f'{BOLD}Token Activity Viewer{RESET}  {CLR_GREY_DIM}(refresh {REFRESH}s, window {int(WINDOW)}s){RESET}')
    print()

    session_rows = build_session_rows(now)
    if not session_rows:
        print(f'{CLR_GREY_DIM}No active sessions{RESET}')
        return

    for sid, buckets, rate, is_idle in session_rows:
        dim = CLR_GREY_DIM if is_idle else ''
        dim_r = RESET if is_idle else ''
        spark = sparkline(buckets) if not is_idle else f'{CLR_GREY_DIM}{"▁" * N_BUCKETS}{RESET}'
        rate_s = fmt_tok(rate).rjust(6)
        print(f'{dim}{sid}{dim_r}  {spark}  {dim}{rate_s} t/m{dim_r}')

    if len(session_rows) >= 2:
        combined_buckets = [0] * N_BUCKETS
        combined_rate = 0
        for _, buckets, rate, _ in session_rows:
            for i, v in enumerate(buckets):
                combined_buckets[i] += v
            combined_rate += rate
        print()
        label = 'COMBINED'.ljust(36)
        spark = sparkline(combined_buckets)
        rate_s = fmt_tok(combined_rate).rjust(6)
        print(f'{BOLD}{label}{RESET}  {spark}  {rate_s} t/m')


def main() -> None:
    try:
        while True:
            render(time.time())
            time.sleep(REFRESH)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
