from datetime import datetime, timezone, tzinfo

import pytest

import statusline_command as sl
from statusline import clock
from helper import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer
RateBucket = sl.RateBucket

_NOW = 1_000_000_000.0  # fixed timestamp for deterministic tests


class TestBurndownTrend:
    """Tests for Renderer.burndown_trend colour buckets and glyph selection."""

    _r = Renderer()
    _W = sl.FIVE_HOUR_MINUTES
    _WU = sl.FIVE_HOUR_WARMUP_MINUTES

    def _trend(self, used_pct: float, delta_minutes: float) -> str:
        resets_at = int(_NOW + delta_minutes * 60)
        return self._r.burndown_trend(used_pct, resets_at, self._W, self._WU, now=_NOW)

    def test_suppressed_no_window(self) -> None:
        assert self._r.burndown_trend(50.0, 0, self._W, self._WU) == ''

    def test_suppressed_expired(self) -> None:
        assert self._r.burndown_trend(50.0, int(_NOW) - 1, self._W, self._WU, now=_NOW) == ''

    def test_suppressed_warmup(self) -> None:
        # 2 min elapsed < 5 min warmup
        resets_at = int(_NOW + 298 * 60)
        assert self._r.burndown_trend(10.0, resets_at, self._W, self._WU, now=_NOW) == ''

    # --- on-pace boundary: small deltas still render a glyph (no neutral dot) ---
    def test_on_pace_small_over_burn(self) -> None:
        # elapsed = 150 -> ideal = 50%; used = 50.3% -> delta = +0.3 -> fast glyph
        assert strip_ansi(self._trend(50.3, 150)) == f'{sl.GLYPH_BURN_FAST} +00.30%'

    def test_on_pace_small_under_burn(self) -> None:
        # used = 49.5% -> delta = -0.5 -> slow glyph
        assert strip_ansi(self._trend(49.5, 150)) == f'{sl.GLYPH_BURN_SLOW} -00.50%'

    def test_exactly_on_pace_uses_slow_glyph(self) -> None:
        # delta == 0 is not > 0, so the slow glyph; sign is '+' (only delta < 0 gets '-')
        assert strip_ansi(self._trend(50.0, 150)) == f'{sl.GLYPH_BURN_SLOW} +00.00%'

    # --- over-burn (delta > 0): fast glyph, '+' sign, zero-padded 05.2f ---
    def test_over_burn_small(self) -> None:
        # delta = +3.0
        assert strip_ansi(self._trend(53.0, 150)) == f'{sl.GLYPH_BURN_FAST} +03.00%'

    def test_over_burn_mid(self) -> None:
        # delta = +8.0
        assert strip_ansi(self._trend(58.0, 150)) == f'{sl.GLYPH_BURN_FAST} +08.00%'

    def test_over_burn_large(self) -> None:
        # delta = +20.0
        assert strip_ansi(self._trend(70.0, 150)) == f'{sl.GLYPH_BURN_FAST} +20.00%'

    # --- under-burn (delta < 0): slow glyph, '-' sign ---
    def test_under_burn_small(self) -> None:
        # delta = -3.0
        assert strip_ansi(self._trend(47.0, 150)) == f'{sl.GLYPH_BURN_SLOW} -03.00%'

    def test_under_burn_mid(self) -> None:
        # delta = -8.0
        assert strip_ansi(self._trend(42.0, 150)) == f'{sl.GLYPH_BURN_SLOW} -08.00%'

    def test_under_burn_large(self) -> None:
        # delta = -20.0
        assert strip_ansi(self._trend(30.0, 150)) == f'{sl.GLYPH_BURN_SLOW} -20.00%'

    # --- colour: continuous gradient mapped from delta, not palette buckets ---
    def test_colour_follows_gradient_mapping(self) -> None:
        # colour is gradient_color(0.5 + delta/50); recompute with the same delta
        delta = 8.0
        out = self._trend(50.0 + delta, 150)
        assert self._r.gradient.gradient_color(0.5 + delta / 50.0) in out

    def test_over_burn_brighter_than_under_burn(self) -> None:
        # Monochrome: burn pressure is read from brightness, not hue. Over-burn
        # maps to a higher gradient position → a brighter (more alarming) grey.
        under = self._r.gradient.gradient_rgb(0.5 + (-20.0) / 50.0)
        over = self._r.gradient.gradient_rgb(0.5 + 20.0 / 50.0)
        assert over[1] > under[1]  # over-burn is brighter


class TestHelperBurndownIntegration:
    """Integration tests for burndown trend inside helper()."""

    _FIXED = datetime(2001, 9, 9, 1, 46, 40, tzinfo=timezone.utc)  # == _NOW = 1_000_000_000.0

    def _patch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fixed = self._FIXED

        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
                if tz is not None:
                    return fixed.astimezone(tz)
                return fixed

        monkeypatch.setattr(clock, 'now', _FakeDatetime.now)
        monkeypatch.setattr(sl.time, 'time', lambda: _NOW)

    def test_pre_warmup_no_trend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch(monkeypatch)
        # 2 min elapsed < 5 min warmup → no trend
        resets_at = int(_NOW + 298 * 60)
        r = Renderer()
        out = r.helper(RateBucket(used_percentage=60.0, resets_at=resets_at))
        stripped = strip_ansi(out)
        assert sl.GLYPH_BURN_FAST not in stripped
        assert '▼' not in stripped
        assert 'T-' in stripped

    def test_mid_window_over_burn_trend_between_pct_and_t(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch(monkeypatch)
        # 150 min elapsed, 150 min left → over-burn
        resets_at = int(_NOW + 150 * 60)
        r = Renderer()
        out = r.helper(RateBucket(used_percentage=60.0, resets_at=resets_at))
        stripped = strip_ansi(out)
        assert '60.0%' in stripped
        assert sl.GLYPH_BURN_FAST in stripped
        t_pos = stripped.index('T-')
        arrow_pos = stripped.index(sl.GLYPH_BURN_FAST)
        assert arrow_pos < t_pos

    def test_expired_window_infinity_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch(monkeypatch)
        past_ts = int(_NOW) - 60
        r = Renderer()
        out = r.helper(RateBucket(used_percentage=80.0, resets_at=past_ts))
        stripped = strip_ansi(out)
        assert '∞' in stripped
        assert 'T-' not in stripped

    def test_helper_uses_five_hour_constants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch(monkeypatch)
        # warmup = 5 min, so at 6 min elapsed trend should appear
        resets_at = int(_NOW + 294 * 60)  # 6 min elapsed
        r = Renderer()
        out = r.helper(RateBucket(used_percentage=60.0, resets_at=resets_at))
        stripped = strip_ansi(out)
        assert sl.GLYPH_BURN_FAST in stripped or '▼' in stripped or sl.GLYPH_BURN_SLOW in stripped


def test_helper_no_usage_no_reset() -> None:
    r = Renderer()
    out = r.helper(RateBucket())
    assert out == '∞'


def test_helper_used_no_reset() -> None:
    r = Renderer()
    out = r.helper(RateBucket(used_percentage=10.0, resets_at=0))
    stripped = strip_ansi(out)
    assert stripped.endswith('∞')
    assert '10.0%' in stripped


def test_helper_reset_in_future(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
            if tz is not None:
                return fixed_now.astimezone(tz)
            return fixed_now

    monkeypatch.setattr(clock, 'now', _FakeDatetime.now)

    future_ts = int(fixed_now.timestamp()) + 3600
    r = Renderer()
    out = r.helper(RateBucket(used_percentage=50.0, resets_at=future_ts))
    stripped = strip_ansi(out)
    assert '50.0%' in stripped
    assert 'T-' in stripped
