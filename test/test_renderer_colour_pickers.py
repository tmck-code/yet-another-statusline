import statusline_command as sl


# Renderer instance shared by all tests in this module
_r = sl.Renderer()


# These assert the *threshold / key-mapping* logic against the active theme's own
# colours (the source of truth), not a hardcoded palette — so they hold for any
# theme, including the monochrome claude-dark where safe/warn/alert are greys.


class TestFillColour:
    def test_0_is_safe(self) -> None:
        assert _r.fill_colour(0) == _r.safe

    def test_69_999_is_safe(self) -> None:
        assert _r.fill_colour(69.999) == _r.safe

    def test_70_is_warn(self) -> None:
        assert _r.fill_colour(70) == _r.warn

    def test_89_999_is_warn(self) -> None:
        assert _r.fill_colour(89.999) == _r.warn

    def test_90_is_alert(self) -> None:
        assert _r.fill_colour(90) == _r.alert

    def test_100_is_alert(self) -> None:
        assert _r.fill_colour(100) == _r.alert

    def test_levels_are_distinct(self) -> None:
        # The three buckets must stay visually separable even in monochrome.
        assert len({_r.safe, _r.warn, _r.alert}) == 3


class TestDayCostColour:
    def test_0_is_safe(self) -> None:
        assert _r.day_cost_colour(0) == _r.safe

    def test_24_999_is_safe(self) -> None:
        assert _r.day_cost_colour(24.999) == _r.safe

    def test_25_is_yellow(self) -> None:
        assert _r.day_cost_colour(25.0) == _r.yellow

    def test_50_is_yellow(self) -> None:
        assert _r.day_cost_colour(50.0) == _r.yellow

    def test_50_01_is_alert(self) -> None:
        assert _r.day_cost_colour(50.01) == _r.alert


class TestModelColour:
    # model_colour maps the model name to a key, then returns that pill's label.
    def test_opus(self) -> None:
        assert _r.model_colour('Opus 4.7') == _r.theme.models['opus'].label

    def test_sonnet_lowercase(self) -> None:
        assert _r.model_colour('sonnet') == _r.theme.models['sonnet'].label

    def test_haiku_upper(self) -> None:
        assert _r.model_colour('HAIKU') == _r.theme.models['haiku'].label

    def test_unknown(self) -> None:
        assert _r.model_colour('gpt-5') == _r.theme.models['other'].label
