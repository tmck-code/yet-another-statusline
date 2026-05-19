import statusline_command as sl


# Renderer instance shared by all tests in this module
_r = sl.Renderer()


# ---------------------------------------------------------------------------
# 5.1  fill_colour — at 0, 69.999, 70, 89.999, 90, 100
# ---------------------------------------------------------------------------

class TestFillColour:
    def test_0_is_ok(self):
        assert _r.fill_colour(0) == sl.CLR_GREEN_OK

    def test_69_999_is_ok(self):
        assert _r.fill_colour(69.999) == sl.CLR_GREEN_OK

    def test_70_is_warn(self):
        assert _r.fill_colour(70) == sl.CLR_WARN

    def test_89_999_is_warn(self):
        assert _r.fill_colour(89.999) == sl.CLR_WARN

    def test_90_is_alert(self):
        assert _r.fill_colour(90) == sl.CLR_ALERT

    def test_100_is_alert(self):
        assert _r.fill_colour(100) == sl.CLR_ALERT


# ---------------------------------------------------------------------------
# 5.2  day_cost_colour — at 0, 24.999, 25.0, 50.0, 50.01
# ---------------------------------------------------------------------------

class TestDayCostColour:
    def test_0_is_ok(self):
        assert _r.day_cost_colour(0) == sl.CLR_GREEN_OK

    def test_24_999_is_ok(self):
        assert _r.day_cost_colour(24.999) == sl.CLR_GREEN_OK

    def test_25_is_yellow(self):
        assert _r.day_cost_colour(25.0) == sl.CLR_YELLOW

    def test_50_is_yellow(self):
        assert _r.day_cost_colour(50.0) == sl.CLR_YELLOW

    def test_50_01_is_alert(self):
        assert _r.day_cost_colour(50.01) == sl.CLR_ALERT


# ---------------------------------------------------------------------------
# 5.3  model_colour — opus, sonnet, haiku, unknown
# ---------------------------------------------------------------------------

class TestModelColour:
    def test_opus(self):
        assert _r.model_colour('Opus 4.7') == sl.CLR_YELLOW

    def test_sonnet_lowercase(self):
        assert _r.model_colour('sonnet') == sl.CLR_GREEN_OK

    def test_haiku_upper(self):
        assert _r.model_colour('HAIKU') == sl.CLR_SKY_BLUE

    def test_unknown(self):
        assert _r.model_colour('gpt-5') == sl.CLR_PURPLE
