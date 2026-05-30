import pytest
import statusline_command as sl



def test_session_cost_sonnet() -> None:
    usage = sl.TranscriptUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    model = sl.Model(id='claude-sonnet-4-6', display_name='Sonnet')
    cost = sl.compute_session_cost(model, usage)
    # 3.00 * 1 + 15.00 * 1 = 18.0
    assert cost == pytest.approx(18.0, abs=1e-9)



def test_session_cost_opus_cache() -> None:
    usage = sl.TranscriptUsage(
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    model = sl.Model(id='opus', display_name='Opus 4.7')  # current Opus: $5 / $25
    cost = sl.compute_session_cost(model, usage)
    # 5.00 * 1.25 + 5.00 * 0.1 = 6.25 + 0.50 = 6.75
    assert cost == pytest.approx(6.75, abs=1e-9)



def test_session_cost_haiku() -> None:
    usage = sl.TranscriptUsage(
        input_tokens=2_000_000,
        output_tokens=1_000_000,
    )
    # Unversioned 'Claude Haiku' resolves to the current Haiku rate: $1 / $5
    model = sl.Model(id='haiku', display_name='Claude Haiku')
    cost = sl.compute_session_cost(model, usage)
    # 1.00 * 2 + 5.00 * 1 = 2.00 + 5.00 = 7.00
    assert cost == pytest.approx(7.00, abs=1e-9)



def test_session_cost_default_zero() -> None:
    usage = sl.TranscriptUsage()
    model = sl.Model()
    cost = sl.compute_session_cost(model, usage)
    assert cost == pytest.approx(0.0, abs=1e-9)



def test_day_cost_via_token_log() -> None:
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


def test_session_cost_display_prefers_host_total_cost_usd() -> None:
    # When Claude Code reports its own session cost, use it verbatim (version-aware,
    # includes modifiers like Fast mode the local estimate cannot see).
    session = sl.SessionInfo(
        model=sl.Model(id='claude-opus-4-7', display_name='Opus 4.7'),
        cost=sl.Cost(total_cost_usd=0.42),
    )
    usage = sl.TranscriptUsage(input_tokens=1_000_000)  # local estimate would differ
    assert sl.session_cost_display(session, usage) == pytest.approx(0.42, abs=1e-9)


def test_session_cost_display_falls_back_when_host_zero() -> None:
    # Before the first API response total_cost_usd is 0 -> fall back to the estimate.
    session = sl.SessionInfo(
        model=sl.Model(id='claude-sonnet-4-6', display_name='Sonnet 4.6'),
        cost=sl.Cost(total_cost_usd=0.0),
    )
    usage = sl.TranscriptUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    # local Sonnet estimate: 3.00 * 1 + 15.00 * 1 = 18.0
    assert sl.session_cost_display(session, usage) == pytest.approx(18.0, abs=1e-9)
