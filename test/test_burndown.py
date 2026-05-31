import time


import statusline_command as sl

burndown_delta = sl.burndown_delta
FIVE_HOUR_MINUTES = sl.FIVE_HOUR_MINUTES
SEVEN_DAY_MINUTES = sl.SEVEN_DAY_MINUTES
FIVE_HOUR_WARMUP_MINUTES = sl.FIVE_HOUR_WARMUP_MINUTES
SEVEN_DAY_WARMUP_MINUTES = sl.SEVEN_DAY_WARMUP_MINUTES


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
