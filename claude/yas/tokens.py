"""Token accounting, rate tracking, and daily-cost log helpers.

Imports:
  - yas.session  for Model and usage types
  - yas.constants for CLAUDE_DIR
"""

from __future__ import annotations

import functools
import time
from typing import Any, TYPE_CHECKING

from yas.constants import CLAUDE_DIR, DT_FLOOR
from yas.session import Model

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# TickRecord (forward-declared here to avoid circular imports — app.py imports
# from layout.py which must not import from app.py)
# ---------------------------------------------------------------------------

class TickRecord:
    __slots__ = ('token_log', 'day_cost', 'tok_rate', 'five_h_rate')

    def __init__(
        self,
        token_log: 'TokenLog',
        day_cost: float,
        tok_rate: int,
        five_h_rate: float | None = None,
    ) -> None:
        self.token_log   = token_log
        self.day_cost    = day_cost
        self.tok_rate    = tok_rate
        self.five_h_rate = five_h_rate


# ---------------------------------------------------------------------------
# TokenAccounting
# ---------------------------------------------------------------------------

class TokenAccounting:
    @staticmethod
    def rates_for(model_name: str) -> tuple[float, float]:
        m = model_name.lower()
        if 'opus' in m:
            return 15.00, 75.00
        if 'haiku' in m:
            return 0.80, 4.00
        if 'fable' in m:
            return 10.00, 50.00
        if 'mythos' in m:
            return 10.00, 50.00
        return 3.00, 15.00

    @staticmethod
    def session_cost(model: Model, usage: Any) -> float:
        rate_in, rate_out = TokenAccounting.rates_for(
            model.display_name or model.id
        )
        cost = (
            usage.input_tokens * rate_in
            + usage.cache_creation_input_tokens * rate_in * 1.25
            + usage.cache_read_input_tokens * rate_in * 0.1
            + usage.output_tokens * rate_out
        )
        return float(cost) / 1_000_000

    @staticmethod
    def day_cost(model: Model, token_log: 'TokenLog') -> float:
        rate_in, rate_out = TokenAccounting.rates_for(
            model.display_name or model.id
        )
        cost = (
            token_log.day_in * rate_in
            + token_log.day_cache_read * rate_in * 0.1
            + token_log.day_out * rate_out
        )
        return cost / 1_000_000


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def compute_session_cost(model: Model, usage: Any) -> float:
    return TokenAccounting.session_cost(model, usage)


def compute_day_cost(model: Model, token_log: 'TokenLog') -> float:
    return TokenAccounting.day_cost(model, token_log)


# ---------------------------------------------------------------------------
# TokenLog
# ---------------------------------------------------------------------------

class TokenLog:
    __slots__ = ('day_in', 'day_cache_read', 'day_out')

    def __init__(self, day_in: int = 0, day_cache_read: int = 0, day_out: int = 0) -> None:
        self.day_in         = day_in
        self.day_cache_read = day_cache_read
        self.day_out        = day_out

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TokenLog):
            return NotImplemented
        return (self.day_in, self.day_cache_read, self.day_out) == \
               (other.day_in, other.day_cache_read, other.day_out)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'TokenLog(day_in={self.day_in}, day_cache_read={self.day_cache_read}, day_out={self.day_out})'

    @classmethod
    def update(cls, session_id: str, today: str, total_in: int, cache_read: int, total_out: int) -> TokenLog:
        log = CLAUDE_DIR / 'statusline-tokens.log'
        lines = []
        if log.exists():
            for ln in log.read_text().splitlines():
                parts = ln.split()
                if len(parts) >= 2 and parts[1] == session_id:
                    continue
                lines.append(ln)
        if session_id and (total_in > 0 or cache_read > 0 or total_out > 0):
            lines.append(f'{today} {session_id} {total_in} {cache_read} {total_out}')
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('\n'.join(lines) + '\n')
        day_in = day_cache_read = day_out = 0
        for ln in lines:
            parts = ln.split()
            if len(parts) < 4 or parts[0] != today:
                continue
            try:
                if len(parts) == 6:
                    day_in += int(parts[2])
                    day_out += int(parts[3])
                elif len(parts) >= 5:
                    day_in += int(parts[2])
                    day_cache_read += int(parts[3])
                    day_out += int(parts[4])
                else:
                    day_in += int(parts[2])
                    day_out += int(parts[3])
            except ValueError:
                pass
        return cls(day_in=day_in, day_cache_read=day_cache_read, day_out=day_out)


# ---------------------------------------------------------------------------
# TokenRate
# ---------------------------------------------------------------------------

@functools.cache
def _token_window() -> float:
    from yas.config import Config
    return Config.load().token_window


class TokenRate:
    # Resolved lazily (see _token_window): evaluating it at import time forced a
    # full Config.load() — and, when a yas.toml exists, the tomllib import — into
    # every startup. None means "resolve from config on first use"; an explicit
    # float (e.g. set by tests) is honoured as-is.
    WINDOW: float | None = None
    KEEP = 300.0

    @classmethod
    def update(cls, session_id: str, total_in: int, total_out: int) -> int:
        if not session_id:
            return 0
        log = CLAUDE_DIR / 'statusline-token-rate.log'
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
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('\n'.join(f'{ts:.3f} {sid} {ti} {to}' for ts, sid, ti, to in rows) + '\n')
        except OSError:
            pass
        window  = cls.WINDOW if cls.WINDOW is not None else _token_window()
        samples = [(ts, ti, to) for ts, sid, ti, to in rows if sid == session_id and now - ts <= window]
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
        log = CLAUDE_DIR / 'statusline-token-rate.log'
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
        log = CLAUDE_DIR / 'statusline-token-rate.log'
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


# ---------------------------------------------------------------------------
# FiveHourRate
# ---------------------------------------------------------------------------

@functools.cache
def _five_hour_rate_window() -> float:
    from yas.config import Config
    return Config.load().five_hour_rate_window


class FiveHourRate:
    """Instantaneous burn-rate sampler for the account-wide 5-hour bucket.

    Mirrors TokenRate, but the series is global (not keyed by session_id) since
    `RateBucket.used_percentage` is account-wide and shared across sessions.
    Samples are filtered to the current `resets_at` so a window rollover starts
    a fresh series and discards stale samples from the expired window.
    """

    WINDOW: float | None = None
    KEEP = 600.0  # >= the max lookback so an in-window sample is never pruned

    @classmethod
    def update(cls, resets_at: int, used_pct: float) -> float | None:
        if not resets_at:
            return None
        log = CLAUDE_DIR / 'statusline-5h-rate.log'
        now = time.time()
        rows: list[tuple[float, int, float]] = []
        if log.exists():
            for ln in log.read_text().splitlines():
                parts = ln.split()
                if len(parts) < 3:
                    continue
                try:
                    ts = float(parts[0])
                    ra = int(parts[1])
                    up = float(parts[2])
                except ValueError:
                    continue
                if now - ts > cls.KEEP:
                    continue
                rows.append((ts, ra, up))
        rows.append((now, resets_at, used_pct))
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('\n'.join(f'{ts:.3f} {ra} {up}' for ts, ra, up in rows) + '\n')
        except OSError:
            pass
        window  = cls.WINDOW if cls.WINDOW is not None else _five_hour_rate_window()
        samples = [(ts, up) for ts, ra, up in rows if ra == resets_at and now - ts <= window]
        if len(samples) < 2:
            return None
        samples.sort()
        t_first, used_first = samples[0]
        t_last, used_last   = samples[-1]
        if (t_last - t_first) < DT_FLOOR:
            return None
        rate = (used_last - used_first) / ((t_last - t_first) / 60)
        return rate if rate > 0 else None


# ---------------------------------------------------------------------------
# RenderTiming
# ---------------------------------------------------------------------------

class RenderTiming:
    """Per-session persistence of the last render's wall-clock duration.

    A render can't know its own total time before it has finished drawing, so
    the bottom-border annotation shows the *previous* run's duration: each run
    reads the last value (to display) at the start and writes its own (for the
    next run) at the end. Keyed by session_id in one log file — like
    TokenRate — so panes don't show each other's timings; lines idle longer
    than KEEP are pruned so the file can't grow without bound.
    """

    KEEP = 300.0

    @classmethod
    def read(cls, session_id: str) -> float | None:
        if not session_id:
            return None
        log = CLAUDE_DIR / 'statusline-render.log'
        if not log.exists():
            return None
        try:
            for ln in log.read_text().splitlines():
                parts = ln.split()
                if len(parts) >= 3 and parts[1] == session_id:
                    return float(parts[2])
        except (OSError, ValueError):
            return None
        return None

    @classmethod
    def write(cls, session_id: str, ms: float) -> None:
        if not session_id:
            return
        log = CLAUDE_DIR / 'statusline-render.log'
        now = time.time()
        rows: list[str] = []
        if log.exists():
            try:
                for ln in log.read_text().splitlines():
                    parts = ln.split()
                    if len(parts) < 3 or parts[1] == session_id:
                        continue
                    try:
                        ts = float(parts[0])
                    except ValueError:
                        continue
                    if now - ts > cls.KEEP:
                        continue
                    rows.append(ln)
            except OSError:
                pass
        rows.append(f'{now:.3f} {session_id} {ms:.1f}')
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('\n'.join(rows) + '\n')
        except OSError:
            pass
