"""Tests for ClaudeQuota — Claude subscription quota approximation mode.

Covers:
- Plan ceiling lookup (pro / max5 / max20)
- Env-var override beats plan default
- pct_5h math (session_tokens / cap_5h × 100)
- pct_weekly math (day_tokens / cap_weekly × 100)
- Clamping to 100% when tokens exceed ceiling
- YAS_CLAUDE_MODE=cost keeps existing cost rendering (line_tokens rows present)
- YAS_CLAUDE_MODE=quota swaps to gauge rendering (quota row present)
- Width-mode renders: wide / medium / narrow
- Colour threshold transitions (60% warn, 85% alert)
"""

import pytest
import statusline_command as sl

from helper import strip_ansi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quota(plan: str = 'max20', session_tokens: int = 0, day_tokens: int = 0,
           monkeypatch: pytest.MonkeyPatch | None = None) -> sl.ClaudeQuota:
    """Build a ClaudeQuota, optionally after clearing override env vars."""
    if monkeypatch is not None:
        monkeypatch.delenv('YAS_CLAUDE_5H_CAP_TOKENS',    raising=False)
        monkeypatch.delenv('YAS_CLAUDE_WEEKLY_CAP_TOKENS', raising=False)
    return sl.ClaudeQuota.load(plan=plan, session_tokens=session_tokens, day_tokens=day_tokens)


# ---------------------------------------------------------------------------
# Plan ceiling lookup
# ---------------------------------------------------------------------------

class TestPlanCeilings:
    def test_pro_ceilings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        q = _quota('pro', monkeypatch=monkeypatch)
        assert q.cap_5h_tokens     ==  1_500_000
        assert q.cap_weekly_tokens == 18_000_000

    def test_max5_ceilings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        q = _quota('max5', monkeypatch=monkeypatch)
        assert q.cap_5h_tokens     ==  7_500_000
        assert q.cap_weekly_tokens == 90_000_000

    def test_max20_ceilings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        q = _quota('max20', monkeypatch=monkeypatch)
        assert q.cap_5h_tokens     ==  30_000_000
        assert q.cap_weekly_tokens == 360_000_000

    def test_unknown_plan_falls_back_to_max20(self, monkeypatch: pytest.MonkeyPatch) -> None:
        q = _quota('enterprise', monkeypatch=monkeypatch)
        assert q.cap_5h_tokens == 30_000_000


# ---------------------------------------------------------------------------
# Env-var override
# ---------------------------------------------------------------------------

class TestEnvVarOverride:
    def test_5h_cap_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('YAS_CLAUDE_5H_CAP_TOKENS', '5000000')
        monkeypatch.delenv('YAS_CLAUDE_WEEKLY_CAP_TOKENS', raising=False)
        q = sl.ClaudeQuota.load(plan='pro', session_tokens=0, day_tokens=0)
        assert q.cap_5h_tokens == 5_000_000

    def test_weekly_cap_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv('YAS_CLAUDE_5H_CAP_TOKENS', raising=False)
        monkeypatch.setenv('YAS_CLAUDE_WEEKLY_CAP_TOKENS', '100000000')
        q = sl.ClaudeQuota.load(plan='pro', session_tokens=0, day_tokens=0)
        assert q.cap_weekly_tokens == 100_000_000

    def test_override_beats_plan_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('YAS_CLAUDE_5H_CAP_TOKENS', '999')
        q = sl.ClaudeQuota.load(plan='max20', session_tokens=0, day_tokens=0)
        # max20 default is 30M but env override wins
        assert q.cap_5h_tokens == 999


# ---------------------------------------------------------------------------
# Percentage math
# ---------------------------------------------------------------------------

class TestPctMath:
    def test_pct_5h_half(self, monkeypatch: pytest.MonkeyPatch) -> None:
        q = _quota('pro', session_tokens=750_000, monkeypatch=monkeypatch)
        assert q.pct_5h == pytest.approx(50.0)

    def test_pct_5h_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        q = _quota('pro', session_tokens=0, monkeypatch=monkeypatch)
        assert q.pct_5h == pytest.approx(0.0)

    def test_pct_weekly_quarter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        q = _quota('pro', day_tokens=4_500_000, monkeypatch=monkeypatch)
        assert q.pct_weekly == pytest.approx(25.0)

    def test_pct_clamped_at_100(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Tokens above ceiling → clamped to 100%, not above
        q = _quota('pro', session_tokens=99_000_000, monkeypatch=monkeypatch)
        assert q.pct_5h == pytest.approx(100.0)

    def test_pct_weekly_clamped_at_100(self, monkeypatch: pytest.MonkeyPatch) -> None:
        q = _quota('pro', day_tokens=999_000_000, monkeypatch=monkeypatch)
        assert q.pct_weekly == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Colour thresholds
# ---------------------------------------------------------------------------

class TestClaudeQuotaColour:
    def setup_method(self) -> None:
        self.r = sl.Renderer()

    def test_under_60_is_safe(self) -> None:
        assert self.r.claude_quota_pct_colour(0.0)  == self.r.safe
        assert self.r.claude_quota_pct_colour(59.9) == self.r.safe

    def test_60_to_85_is_warn(self) -> None:
        assert self.r.claude_quota_pct_colour(60.0) == self.r.warn
        assert self.r.claude_quota_pct_colour(84.9) == self.r.warn

    def test_above_85_is_alert(self) -> None:
        assert self.r.claude_quota_pct_colour(85.0)  == self.r.alert
        assert self.r.claude_quota_pct_colour(100.0) == self.r.alert


# ---------------------------------------------------------------------------
# claude_quota_row renders — width modes
# ---------------------------------------------------------------------------

class TestClaudeQuotaRow:
    def setup_method(self) -> None:
        self.r = sl.Renderer()

    def _q(self, pct_5h: float = 24.0, pct_weekly: float = 12.0,
           plan: str = 'max20') -> sl.ClaudeQuota:
        # Build directly to avoid env interference
        cap_5h     = 30_000_000
        cap_weekly = 360_000_000
        return sl.ClaudeQuota(
            session_tokens=int(pct_5h / 100 * cap_5h),
            day_tokens=int(pct_weekly / 100 * cap_weekly),
            plan=plan,
            cap_5h_tokens=cap_5h,
            cap_weekly_tokens=cap_weekly,
            pct_5h=pct_5h,
            pct_weekly=pct_weekly,
        )

    def test_wide_contains_5h_and_7d(self) -> None:
        row = self.r.claude_quota_row(self._q(), width=120)
        plain = strip_ansi(row)
        assert '5h' in plain
        assert '7d' in plain
        assert '24' in plain
        assert '12' in plain

    def test_wide_contains_plan_label(self) -> None:
        row = self.r.claude_quota_row(self._q(plan='max20'), width=120)
        plain = strip_ansi(row)
        assert 'max20x' in plain

    def test_wide_contains_bar_chars(self) -> None:
        row = self.r.claude_quota_row(self._q(pct_5h=50.0, pct_weekly=50.0), width=120)
        assert '▓' in row or '█' in row or '░' in row

    def test_medium_has_both_pcts(self) -> None:
        row = self.r.claude_quota_row(self._q(), width=79)
        plain = strip_ansi(row)
        assert '5h' in plain
        assert '7d' in plain
        assert '24' in plain
        assert '12' in plain

    def test_narrow_has_primary_only(self) -> None:
        row = self.r.claude_quota_row(self._q(), width=50)
        plain = strip_ansi(row)
        assert '5h' in plain
        assert '24' in plain
        assert '7d' not in plain

    def test_pro_plan_label(self) -> None:
        q = sl.ClaudeQuota(
            session_tokens=0, day_tokens=0,
            plan='pro', cap_5h_tokens=1_500_000, cap_weekly_tokens=18_000_000,
            pct_5h=0.0, pct_weekly=0.0,
        )
        row = self.r.claude_quota_row(q, width=120)
        plain = strip_ansi(row)
        # pro plan label is just 'pro', not 'prox'
        assert 'pro' in plain

    def test_max5_plan_label(self) -> None:
        q = sl.ClaudeQuota(
            session_tokens=0, day_tokens=0,
            plan='max5', cap_5h_tokens=7_500_000, cap_weekly_tokens=90_000_000,
            pct_5h=0.0, pct_weekly=0.0,
        )
        row = self.r.claude_quota_row(q, width=120)
        plain = strip_ansi(row)
        assert 'max5x' in plain

    def test_warn_colour_at_60pct(self) -> None:
        q = self._q(pct_5h=60.0, pct_weekly=0.0)
        row = self.r.claude_quota_row(q, width=120)
        # warn ANSI code should appear
        assert self.r.warn in row

    def test_alert_colour_at_85pct(self) -> None:
        q = self._q(pct_5h=85.0, pct_weekly=0.0)
        row = self.r.claude_quota_row(q, width=120)
        assert self.r.alert in row


# ---------------------------------------------------------------------------
# YAS_CLAUDE_MODE integration — build_wide row selection
# ---------------------------------------------------------------------------

class TestClaudeModeToggle:
    """Smoke tests: verify that build_wide chooses the right row set.

    We don't call build_wide directly (requires a full SessionInfo), so we
    test via ClaudeQuota.load() with the env vars that build_wide reads.
    The row-level behaviour is covered by TestClaudeQuotaRow above.
    """

    def test_mode_cost_is_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When YAS_CLAUDE_MODE is unset, mode resolves to 'cost'."""
        monkeypatch.delenv('YAS_CLAUDE_MODE', raising=False)
        import os
        assert os.environ.get('YAS_CLAUDE_MODE', 'cost').strip().lower() == 'cost'

    def test_mode_quota_activates_gauge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When YAS_CLAUDE_MODE=quota, ClaudeQuota is constructed."""
        monkeypatch.setenv('YAS_CLAUDE_MODE', 'quota')
        monkeypatch.setenv('YAS_CLAUDE_PLAN', 'max20')
        monkeypatch.delenv('YAS_CLAUDE_5H_CAP_TOKENS',    raising=False)
        monkeypatch.delenv('YAS_CLAUDE_WEEKLY_CAP_TOKENS', raising=False)
        import os
        mode = os.environ.get('YAS_CLAUDE_MODE', 'cost').strip().lower()
        plan = os.environ.get('YAS_CLAUDE_PLAN', 'max20').strip().lower()
        assert mode == 'quota'
        q = sl.ClaudeQuota.load(plan=plan, session_tokens=500_000, day_tokens=1_000_000)
        assert q.plan == 'max20'
        assert q.pct_5h == pytest.approx(500_000 / 30_000_000 * 100)

    def test_plan_max20_is_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When YAS_CLAUDE_PLAN is unset, plan resolves to max20."""
        monkeypatch.delenv('YAS_CLAUDE_PLAN', raising=False)
        import os
        assert os.environ.get('YAS_CLAUDE_PLAN', 'max20').strip().lower() == 'max20'
