"""Tests for TokenRate.update and TokenRate.history (disk I/O parsers)."""
import statusline_command as sl


NOW = 1_000_000.0  # fixed "now" for all tests


class FakeTime:
    """Minimal time namespace stub with a settable .time() function."""
    _now = NOW

    @staticmethod
    def time():
        return FakeTime._now


def _log_path(tmp_home):
    return tmp_home / '.claude' / 'statusline-token-rate.log'


def _write_row(path, ts, session_id, total_in, total_out):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as fh:
        fh.write(f'{ts:.3f} {session_id} {total_in} {total_out}\n')


def setup_rate(monkeypatch, tmp_home):
    """Patch time and constants to deterministic values; return log path."""
    monkeypatch.setattr(sl, 'time', FakeTime)
    monkeypatch.setattr(sl.TokenRate, 'WINDOW', 60.0)
    monkeypatch.setattr(sl.TokenRate, 'KEEP', 300.0)
    return _log_path(tmp_home)


def test_single_sample_returns_zero(monkeypatch, tmp_home):
    """3.4 Empty log + first update returns 0."""
    setup_rate(monkeypatch, tmp_home)
    result = sl.TokenRate.update('sess-1', 100, 200)
    assert result == 0


def test_two_samples_in_window_return_delta(monkeypatch, tmp_home):
    """3.5 One synthetic row 30 s ago + new update returns the token delta."""
    log = setup_rate(monkeypatch, tmp_home)
    _write_row(log, NOW - 30, 'sess-1', 100, 200)

    result = sl.TokenRate.update('sess-1', 150, 250)
    # delta = (150 + 250) - (100 + 200) = 100
    assert result == 100


def test_stale_rows_pruned_from_disk(monkeypatch, tmp_home):
    """3.6 Rows older than KEEP are removed from disk."""
    log = setup_rate(monkeypatch, tmp_home)
    _write_row(log, NOW - 9999, 'sess-1', 1, 1)

    sl.TokenRate.update('sess-1', 0, 0)

    content = log.read_text()
    assert f'{NOW - 9999:.3f}' not in content


def test_history_no_samples_returns_zeros(monkeypatch, tmp_home):
    """3.7 history with no samples for the session returns [0]*n_buckets."""
    setup_rate(monkeypatch, tmp_home)
    result = sl.TokenRate.history('sess-1', 5, 60.0)
    assert result == [0, 0, 0, 0, 0]


def test_history_two_samples_same_bucket(monkeypatch, tmp_home):
    """3.8 history with two samples in the same bucket returns one non-zero bucket of the right delta."""
    log = setup_rate(monkeypatch, tmp_home)
    # Place two samples very close together in the last second of the window.
    # With window=60 and n_buckets=5, bucket_size=12s. Both samples near now
    # will land in bucket index 4 (the last bucket).
    _write_row(log, NOW - 1.0, 'sess-1', 100, 200)
    _write_row(log, NOW - 0.5, 'sess-1', 115, 215)

    result = sl.TokenRate.history('sess-1', 5, 60.0)
    assert sum(result) == 30  # (115+215) - (100+200) = 30
    non_zero = [v for v in result if v != 0]
    assert len(non_zero) == 1
    assert non_zero[0] == 30
