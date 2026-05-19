import statusline_command as sl
from conftest import strip_ansi


_r = sl.Renderer()


# ---------------------------------------------------------------------------
# 7.2  gradient_bar
# ---------------------------------------------------------------------------

def test_gradient_bar_zero_fill_is_empty():
    assert _r.gradient_bar(0, 30) == ''


def test_gradient_bar_visible_width():
    # filled=5 → 5 FILLED glyphs + 1 MID leading-edge glyph = 6 visible chars
    result = _r.gradient_bar(5, 30)
    stripped = strip_ansi(result)
    assert sl._visible_width(stripped) == 6


# ---------------------------------------------------------------------------
# 7.3  spec_gradient_bar: idx wraps modulo palette length
# ---------------------------------------------------------------------------

def test_spec_gradient_bar_idx_wraps():
    palette_len = len(sl.Renderer.SPEC_GRADIENTS)
    result_zero = strip_ansi(_r.spec_gradient_bar(3, 30, idx=0))
    result_wrap = strip_ansi(_r.spec_gradient_bar(3, 30, idx=palette_len))
    assert result_zero == result_wrap


def test_spec_gradient_bar_content_is_heavy_glyphs():
    # After stripping ANSI, should be 3 HEAVY glyphs
    stripped = strip_ansi(_r.spec_gradient_bar(3, 30, idx=0))
    assert stripped == sl.BarChars.HEAVY * 3
