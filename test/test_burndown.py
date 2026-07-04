import time
from pathlib import Path

import pytest

import yas.render.metrics as metrics
import yas.tokens as tokens
from yas.constants import (
    FIVE_HOUR_MINUTES,
    SEVEN_DAY_MINUTES,
    FIVE_HOUR_WARMUP_MINUTES,
    SEVEN_DAY_WARMUP_MINUTES,
    DT_FLOOR,
)

burndown_delta   = metrics.burndown_delta
deplete_minutes  = metrics.deplete_minutes
FiveHourRate     = tokens.FiveHourRate


def _resets_at(minutes_from_now: float, now: float = 0.0) -> int:
    if now == 0.0:
        now = time.time()
    return int(now + minutes_from_now * 60)


_NOW = 1_000_000_000.0  # fixed timestamp for deterministic tests


class TestBurndownDeltaSpecExamples:
    def test_over_pace(self) -> None:
        # 5h window, 150 min left → elapsed = 150, ideal = 50%, used = 60% → delta = +10.0
        resets_at = int(_NOW + 150 * 60)
        result = burndown_delta(60.0, resets_at, FIVE_HOUR_MINUTES, FIVE_HOUR_WARMUP_MINUTES, now=_NOW)
        assert result is not None
        assert abs(result - 10.0) < 0.01

    def test_under_pace(self) -> None:
        # 5h window, 150 min left → elapsed = 150, ideal = 50%, used = 30% → delta = -20.0
        resets_at = int(_NOW + 150 * 60)
        result = burndown_delta(30.0, resets_at, FIVE_HOUR_MINUTES, FIVE_HOUR_WARMUP_MINUTES, now=_NOW)
        assert result is not None
        assert abs(result - (-20.0)) < 0.01

    def test_zero_usage_past_warmup(self) -> None:
        # 5h window, 120 min left → elapsed = 180, ideal = 60%, used = 0% → delta = -60.0
        resets_at = int(_NOW + 120 * 60)
        result = burndown_delta(0.0, resets_at, FIVE_HOUR_MINUTES, FIVE_HOUR_WARMUP_MINUTES, now=_NOW)
        assert result is not None
        assert abs(result - (-60.0)) < 0.01


class TestBurndownDeltaSuppressionRules:
    def test_no_window_resets_at_zero(self) -> None:
        assert burndown_delta(50.0, 0, FIVE_HOUR_MINUTES, FIVE_HOUR_WARMUP_MINUTES) is None

    def test_expired_window(self) -> None:
        past_ts = int(_NOW) - 3600
        assert burndown_delta(50.0, past_ts, FIVE_HOUR_MINUTES, FIVE_HOUR_WARMUP_MINUTES, now=_NOW) is None

    def test_warmup_boundary_just_inside(self) -> None:
        # elapsed_minutes = 3 < warmup_minutes = 5 → suppress
        resets_at = int(_NOW + 297 * 60)  # 297 min remaining → elapsed = 3
        assert burndown_delta(10.0, resets_at, FIVE_HOUR_MINUTES, FIVE_HOUR_WARMUP_MINUTES, now=_NOW) is None

    def test_warmup_boundary_just_outside(self) -> None:
        # elapsed_minutes = 6 > warmup_minutes = 5 → not suppressed
        resets_at = int(_NOW + 294 * 60)  # 294 min remaining → elapsed = 6
        result = burndown_delta(10.0, resets_at, FIVE_HOUR_MINUTES, FIVE_HOUR_WARMUP_MINUTES, now=_NOW)
        assert result is not None


class TestBurndownDeltaSevenDay:
    def test_seven_day_window(self) -> None:
        # 7d window half elapsed (5040 min), used 60% → ideal 50% → delta = +10.0
        resets_at = int(_NOW + 5040 * 60)
        result = burndown_delta(60.0, resets_at, SEVEN_DAY_MINUTES, SEVEN_DAY_WARMUP_MINUTES, now=_NOW)
        assert result is not None
        assert abs(result - 10.0) < 0.01

    def test_seven_day_warmup_suppressed(self) -> None:
        # Only 10 min elapsed in 7d window → warmup = 30 min → suppress
        resets_at = int(_NOW + (SEVEN_DAY_MINUTES - 10) * 60)
        assert burndown_delta(5.0, resets_at, SEVEN_DAY_MINUTES, SEVEN_DAY_WARMUP_MINUTES, now=_NOW) is None


# ---------------------------------------------------------------------------
# deplete_minutes (5-hour burn-rate depletion estimate — pure helper)
# ---------------------------------------------------------------------------

class TestDepleteMinutes:
    def test_positive_rate_yields_span(self) -> None:
        # (100 - 60) / 2.0 %/min = 20 minutes
        assert deplete_minutes(60.0, 2.0) == pytest.approx(20.0)

    def test_none_rate_yields_none(self) -> None:
        assert deplete_minutes(60.0, None) is None

    def test_zero_rate_yields_none(self) -> None:
        assert deplete_minutes(60.0, 0.0) is None

    def test_negative_rate_yields_none(self) -> None:
        assert deplete_minutes(60.0, -1.0) is None

    def test_used_pct_100_with_positive_rate_is_zero(self) -> None:
        assert deplete_minutes(100.0, 5.0) == 0.0


# ---------------------------------------------------------------------------
# FiveHourRate (global, resets_at-scoped burn-rate sampler)
# ---------------------------------------------------------------------------

class TestFiveHourRate:
    def setup_method(self) -> None:
        FiveHourRate.WINDOW = 300.0

    def teardown_method(self) -> None:
        FiveHourRate.WINDOW = None

    def test_resets_at_zero_short_circuits(self, tmp_home: Path) -> None:
        assert FiveHourRate.update(0, 50.0) is None

    def test_single_sample_yields_none(self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tokens.time, 'time', lambda: 1_000_000_000.0)
        assert FiveHourRate.update(resets_at=12345, used_pct=10.0) is None

    def test_sub_floor_span_yields_none(self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        now = [1_000_000_000.0]
        monkeypatch.setattr(tokens.time, 'time', lambda: now[0])
        FiveHourRate.update(resets_at=12345, used_pct=10.0)
        now[0] += DT_FLOOR - 1  # under the floor
        result = FiveHourRate.update(resets_at=12345, used_pct=20.0)
        assert result is None

    def test_rising_usage_over_floor_yields_positive_rate(
        self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        now = [1_000_000_000.0]
        monkeypatch.setattr(tokens.time, 'time', lambda: now[0])
        FiveHourRate.update(resets_at=12345, used_pct=10.0)
        now[0] += 120.0  # 2 minutes, past the DT_FLOOR guard
        rate = FiveHourRate.update(resets_at=12345, used_pct=20.0)
        assert rate is not None
        assert rate == pytest.approx((20.0 - 10.0) / (120.0 / 60), abs=0.01)

    def test_global_series_spans_sessions(self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # FiveHourRate.update takes no session_id — two "different session"
        # observations (simulated by two calls) both land in the one series.
        now = [1_000_000_000.0]
        monkeypatch.setattr(tokens.time, 'time', lambda: now[0])
        FiveHourRate.update(resets_at=999, used_pct=5.0)
        now[0] += 90.0
        FiveHourRate.update(resets_at=999, used_pct=8.0)
        now[0] += 90.0
        rate = FiveHourRate.update(resets_at=999, used_pct=15.0)
        assert rate is not None
        assert rate > 0

    def test_resets_at_rollover_discards_stale_series(
        self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        now = [1_000_000_000.0]
        monkeypatch.setattr(tokens.time, 'time', lambda: now[0])
        FiveHourRate.update(resets_at=111, used_pct=50.0)
        now[0] += 120.0
        FiveHourRate.update(resets_at=111, used_pct=60.0)
        now[0] += 120.0
        # New window: only one sample under the new resets_at → no rate yet.
        result = FiveHourRate.update(resets_at=222, used_pct=5.0)
        assert result is None
