"""Per-session token accounting + cost computation.

Persists two append-only logs under config.CLAUDE_DIR:

  - statusline-tokens.log     daily totals per session (model-aware rows)
  - statusline-token-rate.log rolling rate samples (used for burn-rate sparkline
                              + the recently-active in/out indicators)

`TokenLog` rolls the day-tokens log into today's totals (incl. per-model
breakdown for accurate day-cost when sessions span multiple models). `TokenRate`
emits, prunes, and reads back the rate-sample log.

The cost helpers (`compute_session_cost`, `compute_day_cost`,
`session_cost_display`) are thin wrappers around `models.TokenAccounting`.
`session_cost_display` prefers Claude Code's host-reported cost when present
(Fast-mode / data-residency pricing modifiers we can't see locally).

`TranscriptUsage` is a forward reference — it still lives in statusline_command
for now (will move to statusline.transcript in the next extraction). Under
`from __future__ import annotations` the type hints are strings at runtime so
no actual import is needed, only the TYPE_CHECKING block for mypy.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from statusline import config
from statusline.models import Model, SessionInfo, TokenAccounting
from statusline.textutil import _atomic_write_text

if TYPE_CHECKING:
    from statusline_command import TranscriptUsage


def elapsed_from_transcript(transcript_path: str) -> str:
    if not transcript_path:
        return ''
    p = Path(transcript_path)
    if not p.is_file():
        return ''
    try:
        secs = int(time.time() - p.stat().st_mtime)
    except OSError:
        return ''
    h, rem = divmod(secs, 3600)
    m = rem // 60
    return f'{h}h{m}m' if h > 0 else f'{m}m'


def compute_session_cost(model: Model, usage: TranscriptUsage) -> float:
    return TokenAccounting.session_cost(model, usage)


def compute_day_cost(model: Model, token_log: TokenLog) -> float:
    return TokenAccounting.day_cost(model, token_log)


def session_cost_display(session: SessionInfo, usage: TranscriptUsage) -> float:
    '''Session cost to display. Prefer Claude Code's own running estimate
    (cost.total_cost_usd): it is model-version-aware and already reflects pricing
    modifiers (e.g. Fast mode 6x, data residency) that the local rate-table
    estimate cannot see. Fall back to the local estimate only when the host
    value is missing/zero (e.g. before the first API response).'''
    host = session.cost.total_cost_usd
    if host > 0:
        return host
    return compute_session_cost(session.model, usage)


def _model_log_key(model: Model) -> str:
    'Space-free model key for the token log (a space would break the field-delimited row).'
    return (model.id or model.display_name).replace(' ', '-')


@dataclass
class TokenLog:
    day_in: int = 0
    day_cache_read: int = 0
    day_out: int = 0
    # Per-model day totals (model_key -> (in, cache_read, out)) so day cost can
    # price each model separately. Excluded from equality so a hand-built
    # TokenLog(day_in=..., ...) in tests still compares equal.
    by_model: dict[str, tuple[int, int, int]] = field(default_factory=dict, compare=False)

    @classmethod
    def update(cls, session_id: str, today: str, total_in: int, cache_read: int,
               total_out: int, model_id: str = '') -> TokenLog:
        log = config.CLAUDE_DIR / 'statusline-tokens.log'
        old_lines: list[str] = []
        if log.exists():
            try:
                old_lines = log.read_text().splitlines()
            except OSError:
                old_lines = []
        # A v2 row appends a space-free model id; an empty model keeps the legacy
        # 5-field shape (and on-disk format) byte-for-byte unchanged.
        new_row = f'{today} {session_id} {total_in} {cache_read} {total_out}'
        if model_id:
            new_row += f' {model_id}'
        has_tokens = bool(session_id) and (total_in > 0 or cache_read > 0 or total_out > 0)
        # Replace this session's row in place (preserves order, so an unchanged
        # render produces identical content and skips the write — churn fix).
        new_lines: list[str] = []
        replaced = False
        for ln in old_lines:
            parts = ln.split()
            if len(parts) >= 2 and parts[1] == session_id:
                replaced = True
                if has_tokens:
                    new_lines.append(new_row)
            else:
                new_lines.append(ln)
        if has_tokens and not replaced:
            new_lines.append(new_row)
        if new_lines != old_lines:
            _atomic_write_text(log, '\n'.join(new_lines) + '\n')
        return cls._rollup(new_lines, today)

    @staticmethod
    def _rollup(lines: list[str], today: str) -> TokenLog:
        day_in = day_cache_read = day_out = 0
        by_model: dict[str, tuple[int, int, int]] = {}
        for ln in lines:
            parts = ln.split()
            if len(parts) < 4 or parts[0] != today:
                continue
            r_in = r_cache = r_out = 0
            r_model = ''
            try:
                if len(parts) >= 6:
                    r_in, r_cache, r_out, r_model = int(parts[2]), int(parts[3]), int(parts[4]), parts[5]
                elif len(parts) == 5:
                    r_in, r_cache, r_out = int(parts[2]), int(parts[3]), int(parts[4])
                else:  # 4-field legacy: date sid in out
                    r_in, r_out = int(parts[2]), int(parts[3])
            except ValueError:
                continue
            day_in += r_in
            day_cache_read += r_cache
            day_out += r_out
            prev = by_model.get(r_model, (0, 0, 0))
            by_model[r_model] = (prev[0] + r_in, prev[1] + r_cache, prev[2] + r_out)
        return TokenLog(day_in=day_in, day_cache_read=day_cache_read, day_out=day_out, by_model=by_model)



class TokenRate:
    WINDOW = float(os.environ.get('STATUSLINE_TOKEN_WINDOW', '60'))
    KEEP = 300.0

    @classmethod
    def update(cls, session_id: str, total_in: int, total_out: int) -> int:
        if not session_id:
            return 0
        log = config.CLAUDE_DIR / 'statusline-token-rate.log'
        now = time.time()
        rows: list[tuple[float, str, int, int]] = []
        if log.exists():
            for ln in log.read_text().splitlines():
                parts = ln.split()
                if len(parts) < 4:
                    continue
                try:
                    ts = float(parts[0])
                    ti = int(parts[2])
                    to = int(parts[3])
                except ValueError:
                    continue
                if now - ts > cls.KEEP:
                    continue
                rows.append((ts, parts[1], ti, to))
        rows.append((now, session_id, total_in, total_out))
        _atomic_write_text(log, '\n'.join(f'{ts:.3f} {sid} {ti} {to}' for ts, sid, ti, to in rows) + '\n')
        samples = [(ts, ti, to) for ts, sid, ti, to in rows if sid == session_id and now - ts <= cls.WINDOW]
        if len(samples) < 2:
            return 0
        samples.sort()
        _, ti0, to0 = samples[0]
        _, ti1, to1 = samples[-1]
        return max(0, (ti1 + to1) - (ti0 + to0))

    @classmethod
    def history(cls, session_id: str, n_buckets: int, window: float) -> list[int]:
        if n_buckets <= 0 or not session_id:
            return []
        log = config.CLAUDE_DIR / 'statusline-token-rate.log'
        now = time.time()
        samples: list[tuple[float, int, int]] = []
        if log.exists():
            for ln in log.read_text().splitlines():
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
                if sid == session_id and now - ts <= window + window / n_buckets:
                    samples.append((ts, ti, to))
        if len(samples) < 2:
            return [0] * n_buckets
        samples.sort()
        bucket_size = window / n_buckets
        last_bucket  = int(now // bucket_size)
        first_bucket = last_bucket - n_buckets + 1
        buckets = [0] * n_buckets
        for i in range(len(samples) - 1):
            ts0, ti0, to0 = samples[i]
            ts1, ti1, to1 = samples[i + 1]
            delta = max(0, (ti1 + to1) - (ti0 + to0))
            if delta == 0:
                continue
            midpoint = (ts0 + ts1) / 2
            abs_bucket = int(midpoint // bucket_size)
            if first_bucket <= abs_bucket <= last_bucket:
                buckets[abs_bucket - first_bucket] += delta
        return buckets

    @classmethod
    def recently_active(cls, session_id: str, window: float = 10.0) -> tuple[bool, bool]:
        """Return (in_active, out_active) — True if that count grew in the last `window` seconds."""
        if not session_id:
            return False, False
        log = config.CLAUDE_DIR / 'statusline-token-rate.log'
        if not log.exists():
            return False, False
        now = time.time()
        samples: list[tuple[float, int, int]] = []
        for ln in log.read_text().splitlines():
            parts = ln.split()
            if len(parts) < 4:
                continue
            try:
                ts, sid, ti, to = float(parts[0]), parts[1], int(parts[2]), int(parts[3])
            except ValueError:
                continue
            if sid == session_id and now - ts <= window:
                samples.append((ts, ti, to))
        if len(samples) < 2:
            return False, False
        samples.sort()
        ti0, to0 = samples[0][1], samples[0][2]
        ti1, to1 = samples[-1][1], samples[-1][2]
        return ti1 > ti0, to1 > to0
