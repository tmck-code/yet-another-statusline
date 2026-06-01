import yas.renderer as renderer
from yas.constants import (
    CLR_ALERT,
    CLR_GREEN_OK,
    CLR_PURPLE,
    CLR_SKY_BLUE,
    CLR_WARN,
    CLR_YELLOW,
)


# Renderer instance shared by all tests in this module
_r = renderer.Renderer()



class TestFillColour:
    def test_0_is_ok(self) -> None:
        assert _r.fill_colour(0) == CLR_GREEN_OK

    def test_69_999_is_ok(self) -> None:
        assert _r.fill_colour(69.999) == CLR_GREEN_OK

    def test_70_is_warn(self) -> None:
        assert _r.fill_colour(70) == CLR_WARN

    def test_89_999_is_warn(self) -> None:
        assert _r.fill_colour(89.999) == CLR_WARN

    def test_90_is_alert(self) -> None:
        assert _r.fill_colour(90) == CLR_ALERT

    def test_100_is_alert(self) -> None:
        assert _r.fill_colour(100) == CLR_ALERT



class TestDayCostColour:
    def test_0_is_ok(self) -> None:
        assert _r.day_cost_colour(0) == CLR_GREEN_OK

    def test_24_999_is_ok(self) -> None:
        assert _r.day_cost_colour(24.999) == CLR_GREEN_OK

    def test_25_is_yellow(self) -> None:
        assert _r.day_cost_colour(25.0) == CLR_YELLOW

    def test_50_is_yellow(self) -> None:
        assert _r.day_cost_colour(50.0) == CLR_YELLOW

    def test_50_01_is_alert(self) -> None:
        assert _r.day_cost_colour(50.01) == CLR_ALERT



class TestModelColour:
    def test_opus(self) -> None:
        assert _r.model_colour('Opus 4.7') == CLR_YELLOW

    def test_sonnet_lowercase(self) -> None:
        assert _r.model_colour('sonnet') == CLR_GREEN_OK

    def test_haiku_upper(self) -> None:
        assert _r.model_colour('HAIKU') == CLR_SKY_BLUE

    def test_unknown(self) -> None:
        assert _r.model_colour('gpt-5') == CLR_PURPLE
