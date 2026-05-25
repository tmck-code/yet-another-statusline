import statusline_command as sl
from helper import strip_ansi


_r = sl.Renderer()



def test_gradient_bar_zero_fill_is_empty() -> None:
    assert _r.gradient_bar(0, 30) == ''


def test_gradient_bar_visible_width() -> None:
    # filled=5 → 5 FILLED glyphs + 1 MID leading-edge glyph = 6 visible chars
    result = _r.gradient_bar(5, 30)
    stripped = strip_ansi(result)
    assert sl._visible_width(stripped) == 6


def test_gradient_bar_mid_glyph_has_no_background() -> None:
    # Filled cells are painted as space-on-BG for gapless coverage, but the MID
    # leading-edge cap glyph must carry no background: it's emitted after a BG
    # reset (\x1b[49m), so everything from that reset on is BG-free.
    result = _r.gradient_bar(5, 30)
    after_reset = result.split('\x1b[49m', 1)[1]
    assert sl.BarChars.MID in after_reset
    assert '\x1b[48;' not in after_reset


def test_empty_section_fades_leading_chars() -> None:
    # First 3 empty chars ramp from a darker shade up to BAR_EMPTY; remainder
    # share BAR_EMPTY. Smaller `empty` only emits the ramp prefix.
    full = _r._empty_section(10)
    fade = _r._empty_fade_colors()
    for step in fade:
        assert step in full
    assert _r.BAR_EMPTY in full
    assert strip_ansi(full) == sl.BarChars.EMPTY * 10
    assert _r._empty_section(0) == ''
    short = strip_ansi(_r._empty_section(2))
    assert short == sl.BarChars.EMPTY * 2



def test_spec_gradient_bar_idx_wraps() -> None:
    palette_len = len(sl.Renderer.SPEC_GRADIENTS)
    result_zero = strip_ansi(_r.spec_gradient_bar(3, 30, idx=0))
    result_wrap = strip_ansi(_r.spec_gradient_bar(3, 30, idx=palette_len))
    assert result_zero == result_wrap


def test_spec_gradient_bar_content_is_heavy_glyphs() -> None:
    # After stripping ANSI, should be 3 HEAVY glyphs
    stripped = strip_ansi(_r.spec_gradient_bar(3, 30, idx=0))
    assert stripped == sl.BarChars.HEAVY * 3
