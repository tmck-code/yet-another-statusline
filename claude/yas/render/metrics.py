"""Token-usage metric helpers extracted from statusline_command."""

from __future__ import annotations

import time

from yas.constants import subagent_is_terminal, subagent_status
from yas.render.tasks_view import fmt_duration
from yas.render.text import fmt_tok, fmt_tok_fixed


def fmt_lines_pair(read: int, changed: int, *, width: int = 0, fixed: bool = False) -> tuple[str, str]:
    """Format Lines Read / Lines Changed; `width` must be the cohort's measured max, never a guess."""
    fmt = fmt_tok_fixed if fixed else fmt_tok
    read_s    = fmt(read)
    changed_s = fmt(changed)
    if width:
        read_s    = read_s.rjust(width)
        changed_s = changed_s.rjust(width)
    return read_s, changed_s


def subagent_dur_str(sub: object, now: float) -> str:
    """Right-justified elapsed time for a subagent row; not fixed-width, measure it, don't hardcode."""
    status = subagent_status(sub)
    # run_start_ts anchors on the current run (resumed agents append runs to one transcript)
    run_start = getattr(sub, 'run_start_ts', 0.0) or sub.first_timestamp  # type: ignore[attr-defined]
    if subagent_is_terminal(status):
        dur = max(0.0, sub.end_ts - run_start)  # type: ignore[attr-defined]
    else:
        dur = max(0.0, now - run_start) if run_start > 0 else 0.0
    return fmt_duration(dur).rjust(5)


def subagent_type_label(sub: object) -> str:
    """Agent-type text a subagent row displays."""
    return getattr(sub, 'agent_type', '') or '?'


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


def subagent_cluster_field_offsets(
    lines_w: int, *, tok_w: int = 5,
) -> tuple[int, int]:
    """0-indexed offsets from `stats_col` of the tok/lines fields in `· tok · lines`; tok_w=5 is fmt_tok_fixed's max width."""
    sep          = 3  # ' · '
    tok_off      = sep
    lines_off    = tok_off + tok_w + sep
    return tok_off, lines_off


def subagent_cluster_width(lines_w: int, *, tok_w: int = 5) -> int:
    """Visible width of the fully-populated `· tok · lines` stats cluster."""
    dot          = 2  # '· '
    sep          = 3  # ' · '
    lines_full_w = lines_w + 3 + lines_w  # <read> + ' / ' + <changed>
    return dot + tok_w + sep + lines_full_w
