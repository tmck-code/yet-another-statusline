import re

import yas.renderer as renderer_mod
from helper import strip_ansi


_r = renderer_mod.Renderer()

BLOCKS = ' ▁▂▃▄▅▆▇█'  # index 0 = blank, 1..8 = U+2581..U+2588


# Empty / all-zero baselines

def test_sparkline_empty() -> None:
    assert _r.sparkline_1row([]) == ''


def test_sparkline_empty_live() -> None:
    assert _r.sparkline_1row([], live=True) == ''


def test_sparkline_all_zeros_is_blank_cells() -> None:
    # Every value is 0 → level 0 → a blank cell per point.
    assert strip_ansi(_r.sparkline_1row([0, 0, 0])) == '   '


# Level mapping (round(ratio * 8) against the peak)

def test_sparkline_flat_at_max_is_full_blocks() -> None:
    # All equal & non-zero → ratio 1.0 → level 8 → full block.
    assert strip_ansi(_r.sparkline_1row([5, 5, 5])) == '███'


def test_sparkline_rising_series_levels() -> None:
    # peak=4 → ratios .25,.5,.75,1.0 → levels 2,4,6,8.
    assert strip_ansi(_r.sparkline_1row([1, 2, 3, 4])) == '▂▄▆█'


def test_sparkline_falling_series_levels() -> None:
    # peak=4 → ratios 1.0,.75,.5,.25 → levels 8,6,4,2.
    assert strip_ansi(_r.sparkline_1row([4, 3, 2, 1])) == '█▆▄▂'


# Glyph set is only block elements — no U+1FBxx "Symbols for Legacy Computing".

def test_sparkline_uses_only_block_element_glyphs() -> None:
    history = [0, 1, 0, 5, 2, 0, 9, 9, 0, 7, 3]
    glyphs = strip_ansi(_r.sparkline_1row(history))
    assert all(c in BLOCKS for c in glyphs), glyphs
    assert not any(0x1FB00 <= ord(c) <= 0x1FBFF for c in glyphs)


def test_sparkline_width_matches_input() -> None:
    history = [0, 1, 0, 5, 2, 0, 9, 9, 0]
    assert len(strip_ansi(_r.sparkline_1row(history))) == len(history)


# live flag

_RGB_RE = re.compile(r'\033\[38;2;(\d+);(\d+);(\d+)m')


def _first_rgb(row: str) -> tuple[int, int, int]:
    matches = _RGB_RE.findall(row)
    assert matches, f'No RGB escape found in {row!r}'
    r, g, b = matches[0]
    return int(r), int(g), int(b)


def _suffix_rgb_list(row: str, n_drop: int) -> list[tuple[int, int, int]]:
    matches = _RGB_RE.findall(row)
    return [(int(r), int(g), int(b)) for r, g, b in matches[n_drop:]]


def test_sparkline_live_false_identical_to_default() -> None:
    assert _r.sparkline_1row([1, 2, 3, 4]) == _r.sparkline_1row([1, 2, 3, 4], live=False)


def test_sparkline_live_true_dims_first_cell() -> None:
    # Newest sample sits on the LEFT (index 0) and is the live/in-flight cell.
    live = _r.sparkline_1row([1, 2, 3, 4], live=True)
    norm = _r.sparkline_1row([1, 2, 3, 4], live=False)
    lr, lg, lb = _first_rgb(live)
    nr, ng, nb = _first_rgb(norm)
    assert (lr, lg, lb) == (int(nr * 0.5), int(ng * 0.5), int(nb * 0.5))


def test_sparkline_live_true_later_cells_unchanged() -> None:
    live = _r.sparkline_1row([5, 6, 7, 8], live=True)
    norm = _r.sparkline_1row([5, 6, 7, 8], live=False)
    assert _suffix_rgb_list(live, 1) == _suffix_rgb_list(norm, 1)


def test_sparkline_newest_left_oldest_right() -> None:
    # The caller feeds the bucket history newest-first, so index 0 (the newest,
    # live bucket) renders as the LEFTMOST glyph and older samples trail right.
    # peak=8 → ratios 1.0,.5,.25,.125 → levels 8,4,2,1.
    newest_first = [8, 4, 2, 1]
    assert strip_ansi(_r.sparkline_1row(newest_first)) == '█▄▂▁'
    # With live, the leftmost (newest) cell is the dimmed one.
    live = _r.sparkline_1row(newest_first, live=True)
    norm = _r.sparkline_1row(newest_first, live=False)
    assert _first_rgb(live) != _first_rgb(norm)         # leftmost dimmed
    assert _suffix_rgb_list(live, 1) == _suffix_rgb_list(norm, 1)  # rest intact
