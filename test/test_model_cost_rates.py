"""Tests for TokenAccounting.rates_for / Model.cost_rates.

Pricing is keyed by model family + version and verified against the official
pricing page (platform.claude.com, 2026-05-27). UPDATE these expectations (and
the rates_for table) whenever the model catalog or pricing changes.
"""
import statusline_command as sl


class TestModelCostRates:
    # Current Opus (4.5 / 4.6 / 4.7): $5 / $25
    def test_opus_current_rates(self) -> None:
        m = sl.Model(id='claude-opus-4-7', display_name='Opus 4.7')
        assert m.cost_rates == (5.00, 25.00)

    # Legacy Opus 4.1 / 4 (deprecated): $15 / $75
    def test_opus_legacy_4_1_rates(self) -> None:
        assert sl.Model(id='claude-opus-4-1').cost_rates == (15.00, 75.00)

    def test_case_insensitive_opus_4_is_legacy(self) -> None:
        m = sl.Model(id='CLAUDE-OPUS-4', display_name='')
        assert m.cost_rates == (15.00, 75.00)

    # Haiku 4.5: $1 / $5
    def test_haiku_current_rates_via_id(self) -> None:
        m = sl.Model(id='claude-haiku-4-5-20251001', display_name='')
        assert m.cost_rates == (1.00, 5.00)

    def test_case_insensitive_haiku_current(self) -> None:
        m = sl.Model(id='', display_name='HAIKU 4.5')
        assert m.cost_rates == (1.00, 5.00)

    # Haiku 3.5 (retired): $0.80 / $4
    def test_haiku_legacy_3_5_rates(self) -> None:
        assert sl.Model(id='claude-haiku-3-5').cost_rates == (0.80, 4.00)

    # Sonnet (all current): $3 / $15
    def test_sonnet_rates(self) -> None:
        m = sl.Model(id='claude-sonnet-4-6')
        assert m.cost_rates == (3.00, 15.00)

    def test_unknown_model_default_rates(self) -> None:
        m = sl.Model(id='gpt-5')
        assert m.cost_rates == (3.00, 15.00)

    # ---------------------------------------------------------------------------
    # display_name is preferred over id for matching
    # ---------------------------------------------------------------------------

    def test_display_name_preferred_over_id(self) -> None:
        # id says 'haiku-3' but display_name says 'Opus 3' -> legacy opus rates
        m = sl.Model(id='claude-haiku-3', display_name='Opus 3')
        assert m.cost_rates == (15.00, 75.00)

    def test_display_name_empty_falls_back_to_id(self) -> None:
        # display_name empty -> id used for matching; Haiku 4.5 -> current rate
        m = sl.Model(id='claude-haiku-4-5', display_name='')
        assert m.cost_rates == (1.00, 5.00)

    # An unversioned family name resolves to that family's current (latest) rate
    def test_unversioned_haiku_uses_current_rate(self) -> None:
        assert sl.Model(display_name='Claude Haiku').cost_rates == (1.00, 5.00)
