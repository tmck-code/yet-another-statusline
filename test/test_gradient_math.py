import re
import yas.render.gradient as gradient
import yas.renderer as renderer_mod
from yas.constants import CLR_BORDER_OFF


_r = renderer_mod.Renderer()
_ge = gradient.GradientEngine()



def test_gradient_rgb_at_zero() -> None:
    assert _r.gradient_rgb(0.0) == (40, 210, 80)



def test_gradient_rgb_at_one() -> None:
    assert _r.gradient_rgb(1.0) == (170, 60, 210)


def test_gradient_rgb_clamps_above_one() -> None:
    assert _r.gradient_rgb(1.5) == (170, 60, 210)



def test_gradient_rgb_dim() -> None:
    # int(40 * 0.5)=20, int(210 * 0.5)=105, int(80 * 0.5)=40
    assert _r.gradient_rgb(0.0, dim=0.5) == (20, 105, 40)



def test_gradient_color_format() -> None:
    color = _r.gradient_color(0.5)
    assert color.startswith('\033[38;2;')


def test_gradient_color_round_trips_rgb() -> None:
    color = _r.gradient_color(0.5)
    # parse \033[38;2;r;g;bm
    m = re.match(r'\x1b\[38;2;(\d+);(\d+);(\d+)m', color)
    assert m is not None, f'ANSI escape not parsed: {color!r}'
    parsed = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    assert parsed == _r.gradient_rgb(0.5)



def test_grad_at_start_of_full_bar() -> None:
    # col=0, width=10 → t=0/9=0.0; fill=1.0; t <= fill-FADE=0.94 → gradient_color(0.0)
    assert _r.grad_at(0, width=10, fill=1.0) == _r.gradient_color(0.0)



def test_grad_at_past_zero_fill() -> None:
    # fill=0.0 → fill <= 0 → CLR_BORDER_OFF immediately
    assert _r.grad_at(9, width=10, fill=0.0) == CLR_BORDER_OFF


# spark_rgb dim factor

def test_spark_rgb_dim_half() -> None:
    """spark_rgb(t, dim=0.5) == (int(R*0.5), int(G*0.5), int(B*0.5))."""
    r, g, b = _r.spark_rgb(0.7)
    assert _r.spark_rgb(0.7, dim=0.5) == (int(r * 0.5), int(g * 0.5), int(b * 0.5))


def test_spark_rgb_dim_zero() -> None:
    """spark_rgb(t, dim=0.0) == (0, 0, 0) for any t."""
    assert _r.spark_rgb(0.3, dim=0.0) == (0, 0, 0)
    assert _r.spark_rgb(0.7, dim=0.0) == (0, 0, 0)


def test_spark_color_dim_one_matches_default() -> None:
    """spark_color(t, dim=1.0) is byte-identical to spark_color(t)."""
    assert _r.spark_color(0.5) == _r.spark_color(0.5, dim=1.0)


# sparkline_1row — single-row block-element sparkline

_BLOCKS_1ROW = ' ▁▂▃▄▅▆▇█'


def _strip(s: str) -> str:
    return re.sub(r'\033\[[0-9;]*m', '', s)


def test_sparkline_1row_empty() -> None:
    assert _ge.sparkline_1row([]) == ''


def test_sparkline_1row_flat_history_blank_cells() -> None:
    # All zero → every cell is the blank level.
    assert _strip(_ge.sparkline_1row([0, 0, 0, 0])) == '    '


def test_sparkline_1row_glyphs_only_from_block_set() -> None:
    rising  = _strip(_ge.sparkline_1row([1, 2, 3, 4, 5, 6, 7, 8]))
    falling = _strip(_ge.sparkline_1row([8, 7, 6, 5, 4, 3, 2, 1]))
    for glyphs in (rising, falling):
        assert all(c in _BLOCKS_1ROW for c in glyphs), glyphs
        # No U+1FBxx "Symbols for Legacy Computing" glyph appears.
        assert not any(0x1FB00 <= ord(c) <= 0x1FBFF for c in glyphs)
