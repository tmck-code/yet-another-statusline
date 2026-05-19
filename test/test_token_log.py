"""Tests for TokenLog.update (disk I/O parser)."""
import statusline_command as sl


TODAY = '2026-05-19'
YESTERDAY = '2026-05-18'


def _log_path(tmp_home):
    return tmp_home / '.claude' / 'statusline-tokens.log'


def test_empty_log_first_write(tmp_home):
    """2.3 Empty log + first write produces one row and the expected TokenLog."""
    result = sl.TokenLog.update('sess-1', TODAY, 100, 50, 200)
    assert result == sl.TokenLog(day_in=100, day_cache_read=50, day_out=200)
    lines = _log_path(tmp_home).read_text().splitlines()
    assert lines == [f'{TODAY} sess-1 100 50 200']


def test_replace_same_session(tmp_home):
    """2.4 Replacing the same session_id rewrites that row only."""
    log = _log_path(tmp_home)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f'{TODAY} sess-1 100 50 200\n')

    result = sl.TokenLog.update('sess-1', TODAY, 150, 60, 250)
    assert result == sl.TokenLog(day_in=150, day_cache_read=60, day_out=250)
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0] == f'{TODAY} sess-1 150 60 250'


def test_rollup_multiple_sessions(tmp_home):
    """2.5 Rollup across multiple sessions on the same day."""
    log = _log_path(tmp_home)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f'{TODAY} sess-1 100 50 200\n')

    result = sl.TokenLog.update('sess-2', TODAY, 50, 25, 100)
    assert result == sl.TokenLog(day_in=150, day_cache_read=75, day_out=300)
    lines = log.read_text().splitlines()
    assert len(lines) == 2


def test_legacy_4_column_rows(tmp_home):
    """2.6 Legacy 4-column rows (no cache column) are tolerated."""
    log = _log_path(tmp_home)
    log.parent.mkdir(parents=True, exist_ok=True)
    # 4-column: date session_id in out (no cache)
    log.write_text(f'{TODAY} sess-x 100 200\n')

    # Call with zeros so no new row is added for the session
    result = sl.TokenLog.update('sess-1', TODAY, 0, 0, 0)
    # legacy row: day_in=100, day_cache_read=0, day_out=200
    assert result == sl.TokenLog(day_in=100, day_cache_read=0, day_out=200)


def test_other_days_excluded_from_return_preserved_on_disk(tmp_home):
    """2.7 Rows from other days are excluded from the return value but preserved on disk."""
    log = _log_path(tmp_home)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f'{YESTERDAY} old 99 9 99\n')

    result = sl.TokenLog.update('sess-1', TODAY, 10, 1, 20)
    assert result == sl.TokenLog(day_in=10, day_cache_read=1, day_out=20)

    content = log.read_text()
    assert YESTERDAY in content  # yesterday's row preserved
    assert 'old' in content
