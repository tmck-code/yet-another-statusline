import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from claude.mon.lifecycle import Tier, apply_dim, classify, validate_thresholds

NOW = 1_000_000.0
IDLE = timedelta(minutes=5)
REMOVE = timedelta(minutes=15)


class TestClassify:
    def test_young_session_is_bright(self):
        mtime = NOW - 60  # 1 minute old
        assert classify(mtime, NOW, IDLE, REMOVE) == 'bright'

    def test_idle_session_is_dim(self):
        mtime = NOW - 600  # 10 minutes old, between 5m and 15m
        assert classify(mtime, NOW, IDLE, REMOVE) == 'dim'

    def test_old_session_is_removed(self):
        mtime = NOW - 1200  # 20 minutes old, past 15m
        assert classify(mtime, NOW, IDLE, REMOVE) == 'removed'

    def test_age_exactly_idle_after_is_bright(self):
        mtime = NOW - IDLE.total_seconds()
        assert classify(mtime, NOW, IDLE, REMOVE) == 'bright'

    def test_age_exactly_remove_after_is_dim(self):
        mtime = NOW - REMOVE.total_seconds()
        assert classify(mtime, NOW, IDLE, REMOVE) == 'dim'


class TestValidateThresholds:
    def test_valid_thresholds_no_exception(self):
        validate_thresholds(
            include=timedelta(minutes=10),
            idle=timedelta(minutes=2),
            remove=timedelta(minutes=15),
        )

    def test_remove_less_than_idle_raises(self):
        with pytest.raises(ValueError):
            validate_thresholds(
                include=timedelta(minutes=10),
                idle=timedelta(minutes=10),
                remove=timedelta(minutes=5),
            )

    def test_equal_idle_and_remove_no_exception(self):
        validate_thresholds(
            include=timedelta(minutes=5),
            idle=timedelta(minutes=5),
            remove=timedelta(minutes=5),
        )


class TestApplyDim:
    def test_replaces_all_reset_codes(self):
        s = '\x1b[0mhello\x1b[0mworld\x1b[0m'
        result = apply_dim(s)
        assert '\x1b[0m' not in result
        assert result.count('\x1b[0;2m') == 3

    def test_byte_count_matches_original_occurrences(self):
        s = '\x1b[32mfoo\x1b[0m\x1b[34mbar\x1b[0m'
        original_count = s.count('\x1b[0m')
        result = apply_dim(s)
        assert result.count('\x1b[0;2m') == original_count

    def test_no_reset_code_unchanged(self):
        s = '\x1b[32mhello world\x1b[1m'
        assert apply_dim(s) == s

    def test_empty_string_unchanged(self):
        assert apply_dim('') == ''

    def test_plain_string_unchanged(self):
        s = 'no escape codes here'
        assert apply_dim(s) == s
