"""Tests for TokenLog.update (disk I/O parser)."""
from pathlib import Path

import pytest

import statusline_command as sl


TODAY = '2026-05-19'
YESTERDAY = '2026-05-18'


def _log_path(tmp_home: Path) -> Path:
    return tmp_home / '.claude' / 'statusline-tokens.log'


def test_empty_log_first_write(tmp_home: Path) -> None:
    """Empty log + first write produces one row and the expected TokenLog."""
    result = sl.TokenLog.update('sess-1', TODAY, 100, 50, 200)
    assert result == sl.TokenLog(day_in=100, day_cache_read=50, day_out=200)
    lines = _log_path(tmp_home).read_text().splitlines()
    assert lines == [f'{TODAY} sess-1 100 50 200']


def test_replace_same_session(tmp_home: Path) -> None:
    """Replacing the same session_id rewrites that row only."""
    log = _log_path(tmp_home)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f'{TODAY} sess-1 100 50 200\n')

    result = sl.TokenLog.update('sess-1', TODAY, 150, 60, 250)
    assert result == sl.TokenLog(day_in=150, day_cache_read=60, day_out=250)
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0] == f'{TODAY} sess-1 150 60 250'


def test_rollup_multiple_sessions(tmp_home: Path) -> None:
    """Rollup across multiple sessions on the same day."""
    log = _log_path(tmp_home)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f'{TODAY} sess-1 100 50 200\n')

    result = sl.TokenLog.update('sess-2', TODAY, 50, 25, 100)
    assert result == sl.TokenLog(day_in=150, day_cache_read=75, day_out=300)
    lines = log.read_text().splitlines()
    assert len(lines) == 2


def test_legacy_4_column_rows(tmp_home: Path) -> None:
    """Legacy 4-column rows (no cache column) are tolerated."""
    log = _log_path(tmp_home)
    log.parent.mkdir(parents=True, exist_ok=True)
    # 4-column: date session_id in out (no cache)
    log.write_text(f'{TODAY} sess-x 100 200\n')

    # Call with zeros so no new row is added for the session
    result = sl.TokenLog.update('sess-1', TODAY, 0, 0, 0)
    # legacy row: day_in=100, day_cache_read=0, day_out=200
    assert result == sl.TokenLog(day_in=100, day_cache_read=0, day_out=200)


def test_other_days_excluded_from_return_preserved_on_disk(tmp_home: Path) -> None:
    """Rows from other days are excluded from the return value but preserved on disk."""
    log = _log_path(tmp_home)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f'{YESTERDAY} old 99 9 99\n')

    result = sl.TokenLog.update('sess-1', TODAY, 10, 1, 20)
    assert result == sl.TokenLog(day_in=10, day_cache_read=1, day_out=20)

    content = log.read_text()
    assert YESTERDAY in content  # yesterday's row preserved
    assert 'old' in content


def test_v2_stores_model_and_skips_unchanged(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """v2 rows carry a space-free model id; an unchanged re-update does not rewrite."""
    writes = {'n': 0}
    orig = sl._atomic_write_text

    def _counting(p: Path, t: str) -> None:
        writes['n'] += 1
        orig(p, t)

    monkeypatch.setattr(sl, '_atomic_write_text', _counting)

    sl.TokenLog.update('s1', TODAY, 100, 50, 200, 'claude-opus-4-7')
    assert writes['n'] == 1
    assert _log_path(tmp_home).read_text().splitlines() == [f'{TODAY} s1 100 50 200 claude-opus-4-7']

    # identical update -> no rewrite (write-only-on-change)
    sl.TokenLog.update('s1', TODAY, 100, 50, 200, 'claude-opus-4-7')
    assert writes['n'] == 1

    # changed totals -> rewrite
    sl.TokenLog.update('s1', TODAY, 100, 50, 300, 'claude-opus-4-7')
    assert writes['n'] == 2


def test_day_cost_prices_each_model_separately(tmp_home: Path) -> None:
    """A day spanning two models prices each by its own rate, not one rate for all."""
    sl.TokenLog.update('s1', TODAY, 1_000_000, 0, 1_000_000, 'claude-opus-4-7')        # $5 / $25
    log = sl.TokenLog.update('s2', TODAY, 1_000_000, 0, 1_000_000, 'claude-sonnet-4-6')  # $3 / $15
    # opus: 1*5 + 1*25 = 30 ; sonnet: 1*3 + 1*15 = 18 ; total 48 (current model irrelevant)
    cost = sl.compute_day_cost(sl.Model(id='claude-haiku-4-5'), log)
    assert cost == pytest.approx(48.0, abs=1e-9)


def test_day_cost_legacy_rows_use_current_model(tmp_home: Path) -> None:
    """Model-less (v1) rows fall back to the current session's model rate."""
    log = sl.TokenLog.update('s1', TODAY, 1_000_000, 0, 1_000_000)  # no model id -> v1 row
    # priced with the passed (current) model = Sonnet 3/15 -> 1*3 + 1*15 = 18
    cost = sl.compute_day_cost(sl.Model(id='claude-sonnet-4-6'), log)
    assert cost == pytest.approx(18.0, abs=1e-9)
