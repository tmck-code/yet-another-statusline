"""Tests for TokenRate.update and TokenRate.history (disk I/O parsers)."""
from pathlib import Path

import pytest

import statusline.tokens as tokens
from statusline.tokens import TokenRate


NOW = 1_000_000.0  # fixed "now" for all tests


class FakeTime:
    """Minimal time namespace stub with a settable .time() function."""
    _now = NOW

    @staticmethod
    def time() -> float:
        return FakeTime._now


def _log_path(tmp_home: Path) -> Path:
    return tmp_home / '.claude' / 'statusline-token-rate.log'


def _write_row(path: Path, ts: float, session_id: str, total_in: int, total_out: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as fh:
        fh.write(f'{ts:.3f} {session_id} {total_in} {total_out}\n')


def setup_rate(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> Path:
    """Patch time and constants to deterministic values; return log path."""
    monkeypatch.setattr(tokens, 'time', FakeTime)
    monkeypatch.setattr(tokens.TokenRate, 'WINDOW', 60.0)
    monkeypatch.setattr(tokens.TokenRate, 'KEEP', 300.0)
    return _log_path(tmp_home)


def test_single_sample_returns_zero(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    """Empty log + first update returns 0."""
    setup_rate(monkeypatch, tmp_home)
    result = tokens.TokenRate.update('sess-1', 100, 200)
    assert result == 0


def test_two_samples_in_window_return_delta(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    """One synthetic row 30 s ago + new update returns the token delta."""
    log = setup_rate(monkeypatch, tmp_home)
    _write_row(log, NOW - 30, 'sess-1', 100, 200)

    result = tokens.TokenRate.update('sess-1', 150, 250)
    # delta = (150 + 250) - (100 + 200) = 100
    assert result == 100


def test_stale_rows_pruned_from_disk(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    """Rows older than KEEP are removed from disk."""
    log = setup_rate(monkeypatch, tmp_home)
    _write_row(log, NOW - 9999, 'sess-1', 1, 1)

    tokens.TokenRate.update('sess-1', 0, 0)

    content = log.read_text()
    assert f'{NOW - 9999:.3f}' not in content


def test_history_no_samples_returns_zeros(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    """history with no samples for the session returns [0]*n_buckets."""
    setup_rate(monkeypatch, tmp_home)
    result = tokens.TokenRate.history('sess-1', 5, 60.0)
    assert result == [0, 0, 0, 0, 0]


def test_history_two_samples_same_bucket(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    """history with two samples in the same bucket returns one non-zero bucket of the right delta."""
    log = setup_rate(monkeypatch, tmp_home)
    # Place two samples very close together in the last second of the window.
    # With window=60 and n_buckets=5, bucket_size=12s. Both samples near now
    # will land in bucket index 4 (the last bucket).
    _write_row(log, NOW - 1.0, 'sess-1', 100, 200)
    _write_row(log, NOW - 0.5, 'sess-1', 115, 215)

    result = tokens.TokenRate.history('sess-1', 5, 60.0)
    assert sum(result) == 30  # (115+215) - (100+200) = 30
    non_zero = [v for v in result if v != 0]
    assert len(non_zero) == 1
    assert non_zero[0] == 30


# 2.3 – Bucket boundary snapping

def test_history_snaps_bucket_boundaries(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    """Same samples, two now values within same bucket → identical non-zero indices."""
    log = setup_rate(monkeypatch, tmp_home)
    # window=60, n_buckets=5 → bucket_size=12s
    # Place a pair of samples so their midpoint is ~30 s before NOW.
    # Midpoint at NOW-30 → abs_bucket = int((NOW-30)//12)
    _write_row(log, NOW - 31.0, 'sess-1', 0, 0)
    _write_row(log, NOW - 29.0, 'sess-1', 60, 60)

    bucket_size = 60.0 / 5  # 12 s

    # now=T: use the baseline NOW
    FakeTime._now = NOW
    result_t0 = tokens.TokenRate.history('sess-1', 5, 60.0)

    # now=T + 0.4*bucket_size: still in the same bucket for last_bucket
    FakeTime._now = NOW + 0.4 * bucket_size
    result_t1 = tokens.TokenRate.history('sess-1', 5, 60.0)

    nz0 = [i for i, v in enumerate(result_t0) if v != 0]
    nz1 = [i for i, v in enumerate(result_t1) if v != 0]
    assert nz0, 'expected at least one non-zero bucket'
    assert nz0 == nz1, f'non-zero indices differ: {nz0} vs {nz1}'


def test_history_out_of_window_sample_excluded(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    """Out-of-range sample is excluded; sample exactly on oldest edge IS included."""
    log = setup_rate(monkeypatch, tmp_home)
    # window=60, n_buckets=5 → bucket_size=12s
    # first_bucket = int(NOW//12) - 4
    # oldest edge = first_bucket * 12
    bucket_size = 60.0 / 5  # 12 s
    last_bucket  = int(NOW // bucket_size)
    first_bucket = last_bucket - 5 + 1
    oldest_edge  = first_bucket * bucket_size

    # Pair whose midpoint is exactly at oldest_edge → abs_bucket == first_bucket → index 0
    mid_on_edge = oldest_edge
    _write_row(log, mid_on_edge - 0.5, 'sess-1', 0, 0)
    _write_row(log, mid_on_edge + 0.5, 'sess-1', 40, 40)

    # Pair whose midpoint is 2*bucket_size before oldest_edge → excluded
    mid_too_old = oldest_edge - 2 * bucket_size
    _write_row(log, mid_too_old - 0.5, 'sess-1', 1000, 1000)
    _write_row(log, mid_too_old + 0.5, 'sess-1', 1100, 1100)

    FakeTime._now = NOW
    result = tokens.TokenRate.history('sess-1', 5, 60.0)

    # The on-edge pair (delta=80) must appear in index 0.
    assert result[0] == 80, f'expected 80 at index 0, got {result}'
    # The too-old pair's delta (200) must NOT appear anywhere.
    assert sum(result) == 80, f'expected total 80, got {sum(result)} — {result}'


# 2.4 – Same stream, two now values within a bucket → identical non-zero indices

def test_history_same_nonzero_indices_within_bucket(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    """now=T and now=T+0.4*bucket_size yield identical non-zero indices."""
    log = setup_rate(monkeypatch, tmp_home)
    bucket_size = 60.0 / 5  # 12 s

    # Two pairs landing in distinct buckets so there are multiple non-zero indices to compare.
    # Pair 1: midpoint ~42 s before NOW → abs_bucket = int((NOW-42)//12)
    _write_row(log, NOW - 43.0, 'sess-1', 0, 0)
    _write_row(log, NOW - 41.0, 'sess-1', 50, 50)
    # Pair 2: midpoint ~6 s before NOW → lands in last bucket
    _write_row(log, NOW - 7.0, 'sess-1', 50, 50)
    _write_row(log, NOW - 5.0, 'sess-1', 80, 80)

    FakeTime._now = NOW
    result_a = tokens.TokenRate.history('sess-1', 5, 60.0)

    FakeTime._now = NOW + 0.4 * bucket_size
    result_b = tokens.TokenRate.history('sess-1', 5, 60.0)

    nz_a = [i for i, v in enumerate(result_a) if v != 0]
    nz_b = [i for i, v in enumerate(result_b) if v != 0]
    assert nz_a, 'expected non-zero buckets in result_a'
    assert nz_a == nz_b, f'non-zero indices changed: {nz_a} vs {nz_b}'


# 2.5 – Advancing now by exactly one bucket shifts non-zero indices by -1

def test_history_advancing_one_bucket_shifts_indices(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    """now advances by bucket_size → every surviving non-zero index shifts by -1."""
    log = setup_rate(monkeypatch, tmp_home)
    bucket_size = 60.0 / 5  # 12 s

    # Place a pair well inside the window so it survives the shift.
    # Midpoint ~18 s before NOW → index 3 at now=NOW; index 2 at now=NOW+bucket_size.
    _write_row(log, NOW - 19.0, 'sess-1', 0, 0)
    _write_row(log, NOW - 17.0, 'sess-1', 70, 70)

    FakeTime._now = NOW
    result_t = tokens.TokenRate.history('sess-1', 5, 60.0)

    FakeTime._now = NOW + bucket_size
    result_t1 = tokens.TokenRate.history('sess-1', 5, 60.0)

    nz_t  = {i for i, v in enumerate(result_t)  if v != 0}
    nz_t1 = {i for i, v in enumerate(result_t1) if v != 0}

    assert nz_t, 'expected non-zero buckets at now=T'
    # Every index present at T+bucket_size must equal some T-index minus 1.
    for idx in nz_t1:
        assert (idx + 1) in nz_t, (
            f'index {idx} in result_t1 has no matching index {idx+1} in result_t; '
            f'result_t={result_t}, result_t1={result_t1}'
        )


def test_recently_active_no_log(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    monkeypatch.setattr(tokens, 'time', FakeTime)
    in_a, out_a = tokens.TokenRate.recently_active('sess-1', window=10.0)
    assert not in_a and not out_a


def test_recently_active_detects_growth(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    log = setup_rate(monkeypatch, tmp_home)
    FakeTime._now = NOW
    _write_row(log, NOW - 5.0, 'sess-1', 100, 50)
    _write_row(log, NOW - 1.0, 'sess-1', 200, 50)  # in grew, out same
    in_a, out_a = tokens.TokenRate.recently_active('sess-1', window=10.0)
    assert in_a
    assert not out_a


def test_recently_active_both_grow(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    log = setup_rate(monkeypatch, tmp_home)
    FakeTime._now = NOW
    _write_row(log, NOW - 5.0, 'sess-1', 100, 50)
    _write_row(log, NOW - 1.0, 'sess-1', 200, 80)
    in_a, out_a = tokens.TokenRate.recently_active('sess-1', window=10.0)
    assert in_a and out_a


def test_recently_active_stale_data(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> None:
    log = setup_rate(monkeypatch, tmp_home)
    FakeTime._now = NOW
    _write_row(log, NOW - 20.0, 'sess-1', 100, 50)
    _write_row(log, NOW - 15.0, 'sess-1', 200, 80)
    in_a, out_a = tokens.TokenRate.recently_active('sess-1', window=10.0)
    assert not in_a and not out_a
