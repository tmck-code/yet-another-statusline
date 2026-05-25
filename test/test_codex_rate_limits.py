"""Tests for CodexRateLimits — Codex rate-limit gauge (3rd statusline row).

Covers:
- Loading from a synthetic rollouts dir with known values
- Empty rollouts dir → all-None fields
- Stale data → data_age_seconds > threshold
- Color threshold transitions (60%, 85%)
- Width-mode render: full / medium / narrow
"""

import json
import time
from pathlib import Path

import pytest
import statusline_command as sl

from helper import strip_ansi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_rollout(root: Path, year: int, month: int, day: int, events: list[dict]) -> Path:
    """Write a rollout-0.jsonl file under <root>/YYYY/MM/DD/."""
    day_dir = root / f'{year:04d}' / f'{month:02d}' / f'{day:02d}'
    day_dir.mkdir(parents=True, exist_ok=True)
    rollout = day_dir / 'rollout-0.jsonl'
    with rollout.open('w') as fh:
        for evt in events:
            fh.write(json.dumps(evt) + '\n')
    return rollout


def _token_count_event(primary_pct: float, secondary_pct: float,
                        primary_resets: int, secondary_resets: int,
                        plan_type: str = 'pro',
                        ts: str = '2026-05-25T03:47:10.921Z') -> dict:
    return {
        'timestamp': ts,
        'type': 'event_msg',
        'payload': {
            'type': 'token_count',
            'rate_limits': {
                'primary':   {'used_percent': primary_pct,   'window_minutes': 300,   'resets_at': primary_resets},
                'secondary': {'used_percent': secondary_pct, 'window_minutes': 10080, 'resets_at': secondary_resets},
                'plan_type': plan_type,
            },
        },
    }


def _other_event() -> dict:
    return {'timestamp': '2026-05-25T03:00:00.000Z', 'type': 'event_msg', 'payload': {'type': 'other'}}


# ---------------------------------------------------------------------------
# CodexRateLimits.load() — data loading tests
# ---------------------------------------------------------------------------

class TestCodexRateLimitsLoad:
    def test_load_known_values(self, tmp_path: Path) -> None:
        now_epoch = int(time.time())
        primary_resets   = now_epoch + 3600
        secondary_resets = now_epoch + 86400
        _write_rollout(tmp_path, 2026, 5, 25, [
            _token_count_event(12.0, 28.0, primary_resets, secondary_resets),
        ])
        rl = sl.CodexRateLimits.load(tmp_path)
        assert rl.primary_pct   == pytest.approx(12.0)
        assert rl.secondary_pct == pytest.approx(28.0)
        assert rl.primary_resets_at   == primary_resets
        assert rl.secondary_resets_at == secondary_resets
        assert rl.plan_type == 'pro'

    def test_load_picks_last_token_count(self, tmp_path: Path) -> None:
        """When multiple token_count events exist, the LAST one wins."""
        now_epoch = int(time.time())
        _write_rollout(tmp_path, 2026, 5, 25, [
            _token_count_event(5.0, 10.0, now_epoch + 100, now_epoch + 200),
            _other_event(),
            _token_count_event(55.0, 77.0, now_epoch + 150, now_epoch + 250),
        ])
        rl = sl.CodexRateLimits.load(tmp_path)
        assert rl.primary_pct   == pytest.approx(55.0)
        assert rl.secondary_pct == pytest.approx(77.0)

    def test_empty_dir_returns_all_none(self, tmp_path: Path) -> None:
        rl = sl.CodexRateLimits.load(tmp_path)
        assert rl.primary_pct         is None
        assert rl.secondary_pct       is None
        assert rl.primary_resets_at   is None
        assert rl.secondary_resets_at is None
        assert rl.plan_type           is None
        assert rl.data_age_seconds    is None

    def test_no_token_count_events_returns_all_none(self, tmp_path: Path) -> None:
        """A rollout file with only non-token_count events → all None."""
        _write_rollout(tmp_path, 2026, 5, 25, [_other_event(), _other_event()])
        rl = sl.CodexRateLimits.load(tmp_path)
        assert rl.primary_pct is None

    def test_env_var_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        now_epoch = int(time.time())
        _write_rollout(tmp_path, 2026, 5, 25, [
            _token_count_event(33.0, 44.0, now_epoch + 100, now_epoch + 200),
        ])
        monkeypatch.setenv('YAS_CODEX_SESSIONS_DIR', str(tmp_path))
        # load() with no argument should pick up the env var
        rl = sl.CodexRateLimits.load()
        assert rl.primary_pct == pytest.approx(33.0)
        monkeypatch.delenv('YAS_CODEX_SESSIONS_DIR', raising=False)

    def test_data_age_seconds_recent(self, tmp_path: Path) -> None:
        """data_age_seconds should be small for a just-written rollout."""
        now_epoch = int(time.time())
        _write_rollout(tmp_path, 2026, 5, 25, [
            _token_count_event(1.0, 2.0, now_epoch + 100, now_epoch + 200),
        ])
        rl = sl.CodexRateLimits.load(tmp_path)
        # The rollout was written <5s ago; age should be < 10s
        assert rl.data_age_seconds is not None
        assert rl.data_age_seconds < 10.0

    def test_stale_indicator(self, tmp_path: Path) -> None:
        """A rollout older than 3600s should be considered stale."""
        now_epoch = int(time.time())
        rollout = _write_rollout(tmp_path, 2026, 5, 25, [
            _token_count_event(1.0, 2.0, now_epoch + 100, now_epoch + 200),
        ])
        # Back-date the file's mtime by 2 hours
        old_mtime = time.time() - 7200
        import os
        os.utime(rollout, (old_mtime, old_mtime))
        rl = sl.CodexRateLimits.load(tmp_path)
        assert rl.data_age_seconds is not None
        assert rl.data_age_seconds > 3600
        assert rl.is_stale()

    def test_plan_type_free(self, tmp_path: Path) -> None:
        now_epoch = int(time.time())
        _write_rollout(tmp_path, 2026, 5, 25, [
            _token_count_event(0.0, 0.0, now_epoch + 100, now_epoch + 200, plan_type='free'),
        ])
        rl = sl.CodexRateLimits.load(tmp_path)
        assert rl.plan_type == 'free'


# ---------------------------------------------------------------------------
# Color threshold tests
# ---------------------------------------------------------------------------

class TestCodexColorThresholds:
    def setup_method(self) -> None:
        self.r = sl.Renderer()

    def test_under_60_is_safe(self) -> None:
        assert self.r.codex_pct_colour(0.0)   == self.r.safe
        assert self.r.codex_pct_colour(59.9)  == self.r.safe

    def test_60_to_85_is_warn(self) -> None:
        assert self.r.codex_pct_colour(60.0)  == self.r.warn
        assert self.r.codex_pct_colour(84.9)  == self.r.warn

    def test_above_85_is_alert(self) -> None:
        assert self.r.codex_pct_colour(85.0)  == self.r.alert
        assert self.r.codex_pct_colour(100.0) == self.r.alert


# ---------------------------------------------------------------------------
# Render tests — codex_rate_row
# ---------------------------------------------------------------------------

class TestCodexRateRow:
    def setup_method(self) -> None:
        self.r = sl.Renderer()

    def _rl(self, primary: float = 12.0, secondary: float = 28.0,
             plan: str = 'pro') -> sl.CodexRateLimits:
        return sl.CodexRateLimits(
            primary_pct=primary,
            secondary_pct=secondary,
            primary_resets_at=None,
            secondary_resets_at=None,
            plan_type=plan,
            data_age_seconds=30.0,
        )

    def test_full_mode_contains_5h_and_7d(self) -> None:
        row = self.r.codex_rate_row(self._rl(), width=120)
        plain = strip_ansi(row)
        assert '5h' in plain
        assert '7d' in plain
        assert '12' in plain   # primary pct
        assert '28' in plain   # secondary pct
        assert 'pro' in plain

    def test_full_mode_contains_plan(self) -> None:
        row = self.r.codex_rate_row(self._rl(plan='free'), width=120)
        plain = strip_ansi(row)
        assert 'free' in plain

    def test_medium_mode_has_both_pcts(self) -> None:
        row = self.r.codex_rate_row(self._rl(), width=79)
        plain = strip_ansi(row)
        assert '5h' in plain
        assert '7d' in plain
        assert '12' in plain
        assert '28' in plain

    def test_narrow_mode_has_primary_only(self) -> None:
        row = self.r.codex_rate_row(self._rl(), width=50)
        plain = strip_ansi(row)
        assert '5h' in plain
        assert '12' in plain
        # In narrow mode we may omit 7d label and secondary pct entirely
        assert '7d' not in plain

    def test_no_data_state(self) -> None:
        rl = sl.CodexRateLimits(
            primary_pct=None, secondary_pct=None,
            primary_resets_at=None, secondary_resets_at=None,
            plan_type=None, data_age_seconds=None,
        )
        row = self.r.codex_rate_row(rl, width=120)
        plain = strip_ansi(row)
        assert 'no codex data' in plain.lower() or plain.strip() == ''

    def test_stale_shows_indicator(self) -> None:
        rl = sl.CodexRateLimits(
            primary_pct=5.0, secondary_pct=10.0,
            primary_resets_at=None, secondary_resets_at=None,
            plan_type='pro', data_age_seconds=7200.0,
        )
        row = self.r.codex_rate_row(rl, width=120)
        plain = strip_ansi(row)
        # Stale indicator: either "stale" text or a warning symbol
        assert 'stale' in plain.lower() or '?' in plain or '⚠' in plain

    def test_bar_chars_present_in_full_mode(self) -> None:
        """Full mode should contain filled/empty bar chars."""
        row = self.r.codex_rate_row(self._rl(primary=50.0, secondary=50.0), width=120)
        # Bar characters: ▓ (heavy) or █ (filled) and ░ (empty)
        assert '▓' in row or '█' in row or '░' in row
