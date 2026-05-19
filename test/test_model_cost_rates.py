import statusline_command as sl


# ---------------------------------------------------------------------------
# 4.1  Model.cost_rates — opus, haiku, sonnet, unknown
# ---------------------------------------------------------------------------

class TestModelCostRates:
    def test_opus_rates(self):
        m = sl.Model(id='claude-opus-4-7', display_name='Opus 4.7')
        assert m.cost_rates == (15.00, 75.00)

    def test_haiku_rates_via_id(self):
        m = sl.Model(id='claude-haiku-4-5-20251001', display_name='')
        assert m.cost_rates == (0.80, 4.00)

    def test_sonnet_rates(self):
        m = sl.Model(id='claude-sonnet-4-6')
        assert m.cost_rates == (3.00, 15.00)

    def test_unknown_model_default_rates(self):
        m = sl.Model(id='gpt-5')
        assert m.cost_rates == (3.00, 15.00)

    # ---------------------------------------------------------------------------
    # 4.2  display_name is preferred over id for matching
    # ---------------------------------------------------------------------------

    def test_display_name_preferred_over_id(self):
        # id says 'haiku' but display_name says 'Opus' → opus rates
        m = sl.Model(id='claude-haiku-3', display_name='Opus 3')
        assert m.cost_rates == (15.00, 75.00)

    def test_display_name_empty_falls_back_to_id(self):
        # display_name empty → id used for matching
        m = sl.Model(id='claude-haiku-4-5', display_name='')
        assert m.cost_rates == (0.80, 4.00)

    def test_case_insensitive_opus(self):
        m = sl.Model(id='CLAUDE-OPUS-4', display_name='')
        assert m.cost_rates == (15.00, 75.00)

    def test_case_insensitive_haiku(self):
        m = sl.Model(id='', display_name='HAIKU 4.5')
        assert m.cost_rates == (0.80, 4.00)
