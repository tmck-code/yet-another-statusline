import pytest
import statusline_command as sl


# ---------------------------------------------------------------------------
# 3.2  Sonnet: input=1_000_000, output=1_000_000 -> 18.0
# ---------------------------------------------------------------------------

def test_session_cost_sonnet():
    usage = sl.TranscriptUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    model = sl.Model(id='claude-sonnet-4-6', display_name='Sonnet')
    cost = sl.compute_session_cost(model, usage)
    # 3.00 * 1 + 15.00 * 1 = 18.0
    assert cost == pytest.approx(18.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 3.3  Opus: cache_creation=1_000_000, cache_read=1_000_000 -> 20.25
# ---------------------------------------------------------------------------

def test_session_cost_opus_cache():
    usage = sl.TranscriptUsage(
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    model = sl.Model(id='opus', display_name='Opus 4.7')
    cost = sl.compute_session_cost(model, usage)
    # 15.00 * 1.25 + 15.00 * 0.1 = 18.75 + 1.50 = 20.25
    assert cost == pytest.approx(20.25, abs=1e-9)


# ---------------------------------------------------------------------------
# 3.4  Haiku: input=2_000_000, output=1_000_000 -> 5.60
# ---------------------------------------------------------------------------

def test_session_cost_haiku():
    usage = sl.TranscriptUsage(
        input_tokens=2_000_000,
        output_tokens=1_000_000,
    )
    model = sl.Model(id='haiku', display_name='Claude Haiku')
    cost = sl.compute_session_cost(model, usage)
    # 0.80 * 2 + 4.00 * 1 = 1.60 + 4.00 = 5.60
    assert cost == pytest.approx(5.60, abs=1e-9)


# ---------------------------------------------------------------------------
# 3.5  Default -> session_cost == 0.0
# ---------------------------------------------------------------------------

def test_session_cost_default_zero():
    usage = sl.TranscriptUsage()
    model = sl.Model()
    cost = sl.compute_session_cost(model, usage)
    assert cost == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 3.6  day_cost via TokenLog
# ---------------------------------------------------------------------------

def test_day_cost_via_token_log():
    # Use sonnet rates: rate_in=3.00, rate_out=15.00
    # day_in=500_000, day_cache_read=200_000, day_out=100_000
    # expected = (500_000 * 3.00 + 200_000 * 3.00 * 0.1 + 100_000 * 15.00) / 1_000_000
    #           = (1_500_000 + 60_000 + 1_500_000) / 1_000_000
    #           = 3_060_000 / 1_000_000
    #           = 3.06
    log = sl.TokenLog(day_in=500_000, day_cache_read=200_000, day_out=100_000)
    model = sl.Model(id='claude-sonnet-4-6', display_name='Sonnet')
    cost = sl.compute_day_cost(model, log)
    assert cost == pytest.approx(3.06, abs=1e-9)
