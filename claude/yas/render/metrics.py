"""Token-usage metric helpers extracted from statusline_command."""

from __future__ import annotations

import time


def burndown_delta(
    used_pct: float,
    resets_at: int,
    window_minutes: int,
    warmup_minutes: int,
    now: float | None = None,
) -> float | None:
    if not resets_at:
        return None
    t = now if now is not None else time.time()
    if t >= resets_at:
        return None
    window_start_ts = resets_at - window_minutes * 60
    elapsed_minutes = (t - window_start_ts) / 60
    if elapsed_minutes < warmup_minutes:
        return None
    ideal_pct = (elapsed_minutes / window_minutes) * 100
    return used_pct - ideal_pct


def deplete_minutes(used_pct: float, rate_per_min: float | None) -> float | None:
    """Minutes until the 5-hour bucket hits 100% at the given instantaneous rate.

    Distinct from `burndown_delta` (a pace-vs-ideal deviation) — this is a pure
    projection from a %/min rate. Returns None when the rate is unavailable or
    non-positive (no depletion estimate).
    """
    if not rate_per_min or rate_per_min <= 0:
        return None
    return (100 - used_pct) / rate_per_min


def subagent_avg_tpm(
    total_input: int,
    output: int,
    first_timestamp: float,
    now: float,
    floor_seconds: float = 3.0,
) -> int | None:
    if first_timestamp == 0 or now - first_timestamp < floor_seconds:
        return None
    return round((total_input + output) / ((now - first_timestamp) / 60))


def subagent_share(sub_inout: int, session_inout: int) -> float | None:
    if session_inout <= 0:
        return None
    return sub_inout / session_inout
