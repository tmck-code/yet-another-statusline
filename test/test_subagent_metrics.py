import pytest

import statusline_command as sl
import statusline.metrics as metrics
from statusline.metrics import subagent_avg_tpm, subagent_share


class TestSubagentAvgTpm:
    def test_normal_case(self) -> None:
        # 300 input + 300 output = 600 tokens over 120 seconds (2 min) = 300 t/m
        result = subagent_avg_tpm(
            total_input=300,
            output=300,
            first_timestamp=1_000_000.0,
            now=1_000_120.0,
            floor_seconds=3.0,
        )
        assert result == 300

    def test_returns_none_when_first_timestamp_zero(self) -> None:
        result = subagent_avg_tpm(
            total_input=1000,
            output=500,
            first_timestamp=0,
            now=60.0,
        )
        assert result is None

    def test_returns_none_when_elapsed_below_floor(self) -> None:
        # elapsed = 2.0s < floor_seconds = 3.0s
        result = subagent_avg_tpm(
            total_input=1000,
            output=500,
            first_timestamp=10.0,
            now=12.0,
        )
        assert result is None

    def test_returns_none_when_elapsed_just_below_floor(self) -> None:
        # elapsed = 2.99s < floor_seconds = 3.0s → None
        result = subagent_avg_tpm(
            total_input=1000,
            output=500,
            first_timestamp=10.0,
            now=12.99,
        )
        assert result is None

    def test_returns_value_just_above_floor(self) -> None:
        # elapsed = 3.01s > 3.0s floor → should return a value
        result = subagent_avg_tpm(
            total_input=1000,
            output=500,
            first_timestamp=10.0,
            now=13.01,
        )
        assert result is not None


class TestSubagentShare:
    def test_normal_case(self) -> None:
        result = subagent_share(sub_inout=300, session_inout=1000)
        assert result == pytest.approx(0.3)

    def test_shares_sum_to_one(self) -> None:
        # main_inout=500, sub1_inout=300, sub2_inout=200; session_inout=1000
        session_inout = 1000
        main_inout = 500
        sub1_inout = 300
        sub2_inout = 200

        main_share = subagent_share(main_inout, session_inout)
        sub1_share = subagent_share(sub1_inout, session_inout)
        sub2_share = subagent_share(sub2_inout, session_inout)

        assert main_share is not None
        assert sub1_share is not None
        assert sub2_share is not None
        assert main_share + sub1_share + sub2_share == pytest.approx(1.0)

    def test_returns_none_when_session_inout_zero(self) -> None:
        result = subagent_share(sub_inout=300, session_inout=0)
        assert result is None

    def test_returns_none_when_session_inout_negative(self) -> None:
        result = subagent_share(sub_inout=300, session_inout=-1)
        assert result is None
