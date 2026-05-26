"""Tests for _effective_soft_limit — context gauge scales to model context window.

Covers:
- _effective_soft_limit returns 75% of context_window_size for large models
- _effective_soft_limit returns legacy 150K floor for 200K-and-below models
- _effective_soft_limit returns legacy 150K fallback when context_window_size is 0
- context_line() renders proportional % for 1M-context models (not overflowed)
- context_line() still triggers warning zone for 200K models near soft limit
- context_line_compact() mirrors the same proportional/warning behaviour
- build_wide / build_medium / build_narrow LayoutSpec.fill reflects scaled limit
"""

import re

import pytest
import statusline_command as sl

from helper import strip_ansi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(total_tokens: int, context_window_size: int) -> sl.ContextWindow:
    """Build a ContextWindow with all tokens as input."""
    return sl.ContextWindow(
        total_input_tokens=total_tokens,
        total_output_tokens=0,
        context_window_size=context_window_size,
    )


# ---------------------------------------------------------------------------
# _effective_soft_limit unit tests
# ---------------------------------------------------------------------------

class TestEffectiveSoftLimit:
    def test_1m_model_returns_750k(self) -> None:
        ctx = _ctx(0, context_window_size=1_000_000)
        assert sl._effective_soft_limit(ctx) == 750_000

    def test_200k_model_returns_150k_floor(self) -> None:
        # 75% of 200K = 150K, which equals the floor exactly
        ctx = _ctx(0, context_window_size=200_000)
        assert sl._effective_soft_limit(ctx) == 150_000

    def test_unknown_size_returns_150k_fallback(self) -> None:
        ctx = _ctx(0, context_window_size=0)
        assert sl._effective_soft_limit(ctx) == 150_000

    def test_small_window_floor_wins(self) -> None:
        # 75% of 100K = 75K, which is below 150K floor
        ctx = _ctx(0, context_window_size=100_000)
        assert sl._effective_soft_limit(ctx) == 150_000


# ---------------------------------------------------------------------------
# context_line rendering — proportional fill for 1M models
# ---------------------------------------------------------------------------

class TestContextLineSoftLimit:
    def setup_method(self) -> None:
        self.r = sl.Renderer()

    def test_1m_model_170k_tokens_shows_proportional_pct(self) -> None:
        # 170K / 750K soft_limit = 22.7% → should show 22% or 23%, NOT 113%
        ctx = _ctx(170_000, context_window_size=1_000_000)
        line = self.r.context_line(ctx, available=76)
        plain = strip_ansi(line)
        assert '22%' in plain or '23%' in plain, (
            f'Expected ~22-23% for 170K on 1M-context model, got: {plain!r}'
        )
        assert '113%' not in plain, (
            f'Old broken value 113% should not appear; got: {plain!r}'
        )

    def test_200k_model_180k_tokens_triggers_warning(self) -> None:
        # 180K / 150K soft_limit = 120% → warning zone (>=100% of soft)
        ctx = _ctx(180_000, context_window_size=200_000)
        line = self.r.context_line(ctx, available=76)
        plain = strip_ansi(line)
        # The headline pct_soft should be >= 100 (e.g. "120%")
        pct_values = [int(m) for m in re.findall(r'(\d+)%', plain)]
        assert any(v >= 100 for v in pct_values), (
            f'Expected >=100% soft pct for 180K on 200K model, got pcts: {pct_values} in {plain!r}'
        )


# ---------------------------------------------------------------------------
# context_line_compact rendering — mirrors proportional/warning behaviour
# ---------------------------------------------------------------------------

class TestContextLineCompactSoftLimit:
    def setup_method(self) -> None:
        self.r = sl.Renderer()

    def test_1m_model_170k_tokens_shows_proportional_pct(self) -> None:
        ctx = _ctx(170_000, context_window_size=1_000_000)
        line = self.r.context_line_compact(ctx, available=40)
        plain = strip_ansi(line)
        assert '22%' in plain or '23%' in plain, (
            f'Expected ~22-23% for 170K on 1M-context model (compact), got: {plain!r}'
        )
        assert '113%' not in plain, (
            f'Old broken value 113% should not appear (compact); got: {plain!r}'
        )

    def test_200k_model_180k_tokens_triggers_warning(self) -> None:
        ctx = _ctx(180_000, context_window_size=200_000)
        line = self.r.context_line_compact(ctx, available=40)
        plain = strip_ansi(line)
        pct_values = [int(m) for m in re.findall(r'(\d+)%', plain)]
        assert any(v >= 100 for v in pct_values), (
            f'Expected >=100% soft pct for 180K on 200K model (compact), got pcts: {pct_values} in {plain!r}'
        )


# ---------------------------------------------------------------------------
# build_wide / build_medium / build_narrow — LayoutSpec.fill uses scaled limit
#
# fill = min(total_tokens / _effective_soft_limit(ctx), 1.0)
# On a 1M-context model with 170K tokens: 170_000 / 750_000 ≈ 0.2267
# With bare SOFT_LIMIT (150K):            170_000 / 150_000 ≈ 1.133 → clamped 1.0
#
# We assert fill < 0.5, which is satisfied by ~0.227 and would NOT be satisfied
# by the clamped 1.0 from the old bug.  The exact expected value 170/750 ≈ 0.2267
# is also checked to within floating-point tolerance.
# ---------------------------------------------------------------------------

def _session_1m(total_tokens: int) -> sl.SessionInfo:
    """Minimal SessionInfo: 1M context window, given total_tokens as input."""
    ctx = sl.ContextWindow(
        total_input_tokens=total_tokens,
        total_output_tokens=0,
        context_window_size=1_000_000,
    )
    session = sl.SessionInfo()
    session.context_window = ctx
    return session


class TestBuildFunctionsSoftLimit:
    """build_wide/medium/narrow LayoutSpec.fill must use _effective_soft_limit."""

    def setup_method(self) -> None:
        self.r = sl.Renderer()

    def test_build_wide_does_not_overflow_on_1m_model(self) -> None:
        # 170K tokens on 1M-context model → soft_limit=750K → fill≈0.227, not 1.0
        session = _session_1m(170_000)
        spec = sl.build_wide(session, width=120, r=self.r)
        expected_fill = 170_000 / 750_000
        assert spec.fill < 0.5, (
            f'fill={spec.fill:.4f} should be ~0.227 on 1M model; old bug produced 1.0'
        )
        assert abs(spec.fill - expected_fill) < 1e-6, (
            f'fill={spec.fill:.6f}, expected {expected_fill:.6f}'
        )

    def test_build_medium_does_not_overflow_on_1m_model(self) -> None:
        session = _session_1m(170_000)
        spec = sl.build_medium(session, width=68, r=self.r)
        expected_fill = 170_000 / 750_000
        assert spec.fill < 0.5, (
            f'fill={spec.fill:.4f} should be ~0.227 on 1M model; old bug produced 1.0'
        )
        assert abs(spec.fill - expected_fill) < 1e-6, (
            f'fill={spec.fill:.6f}, expected {expected_fill:.6f}'
        )

    def test_build_narrow_does_not_overflow_on_1m_model(self) -> None:
        session = _session_1m(170_000)
        spec = sl.build_narrow(session, width=48, r=self.r)
        expected_fill = 170_000 / 750_000
        assert spec.fill < 0.5, (
            f'fill={spec.fill:.4f} should be ~0.227 on 1M model; old bug produced 1.0'
        )
        assert abs(spec.fill - expected_fill) < 1e-6, (
            f'fill={spec.fill:.6f}, expected {expected_fill:.6f}'
        )
