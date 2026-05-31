import pytest
import statusline_command as sl
import statusline.renderer as renderer

_r = renderer.Renderer()

@pytest.mark.parametrize('tokens,expected', [
    (49_999,  _r.safe),
    (50_000,  _r.safe),
    (50_001,  _r.yellow),
    (79_999,  _r.yellow),
    (80_000,  _r.yellow),
    (80_001,  _r.warn),
    (149_999, _r.warn),
    (150_000, _r.warn),
    (150_001, _r.alert),
])
def test_risk_zone_color(tokens: int, expected: str) -> None:
    assert _r.risk_zone_color(tokens) == expected
