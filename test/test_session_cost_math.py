import pytest
import yas.tokens as tokens
from yas.session import Model
from yas.tokens import TokenLog, compute_session_cost, compute_day_cost
from yas.info.transcript import TranscriptUsage



def test_session_cost_sonnet() -> None:
    usage = TranscriptUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    model = Model(id='claude-sonnet-4-6', display_name='Sonnet')
    cost = compute_session_cost(model, usage)
    # 3.00 * 1 + 15.00 * 1 = 18.0
    assert cost == pytest.approx(18.0, abs=1e-9)



def test_session_cost_opus_cache() -> None:
    usage = TranscriptUsage(
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    model = Model(id='opus', display_name='Opus 4.7')
    cost = compute_session_cost(model, usage)
    # 15.00 * 1.25 + 15.00 * 0.1 = 18.75 + 1.50 = 20.25
    assert cost == pytest.approx(20.25, abs=1e-9)



def test_session_cost_haiku() -> None:
    usage = TranscriptUsage(
        input_tokens=2_000_000,
        output_tokens=1_000_000,
    )
    model = Model(id='haiku', display_name='Claude Haiku')
    cost = compute_session_cost(model, usage)
    # 0.80 * 2 + 4.00 * 1 = 1.60 + 4.00 = 5.60
    assert cost == pytest.approx(5.60, abs=1e-9)



def test_session_cost_default_zero() -> None:
    usage = TranscriptUsage()
    model = Model()
    cost = compute_session_cost(model, usage)
    assert cost == pytest.approx(0.0, abs=1e-9)



def test_day_cost_via_token_log() -> None:
    # Use sonnet rates: rate_in=3.00, rate_out=15.00
    # day_in=500_000, day_cache_read=200_000, day_out=100_000
    # expected = (500_000 * 3.00 + 200_000 * 3.00 * 0.1 + 100_000 * 15.00) / 1_000_000
    #           = (1_500_000 + 60_000 + 1_500_000) / 1_000_000
    #           = 3_060_000 / 1_000_000
    #           = 3.06
    log = TokenLog(day_in=500_000, day_cache_read=200_000, day_out=100_000)
    model = Model(id='claude-sonnet-4-6', display_name='Sonnet')
    cost = compute_day_cost(model, log)
    assert cost == pytest.approx(3.06, abs=1e-9)
