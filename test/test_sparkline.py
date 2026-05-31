import re

import statusline.constants as constants
import statusline.renderer as renderer_mod
from helper import strip_ansi


_r = renderer_mod.Renderer()


# Empty / all-zero baselines

def test_sparkline_empty() -> None:
    assert _r.sparkline([]) == ('', '')


def test_sparkline_all_zeros() -> None:
    # Every cell stays flat: top blank, bottom ▁ stubs.
    top, bot = _r.sparkline([0, 0, 0])
    assert strip_ansi(top) == '   '
    assert strip_ansi(bot) == '▁▁▁'


def test_sparkline_monotone_flat_at_max() -> None:
    # All cells equal and non-zero: first cell rises from implicit 0,
    # later equal cells render as flat █ blocks.
    top, bot = _r.sparkline([5, 5, 5])
    assert strip_ansi(top) == f'{constants.SPARK_RISE_TOP}██'
    assert strip_ansi(bot) == f'{constants.SPARK_RISE_TALL}██'


# Neighbor-aware slope behavior

def test_sparkline_isolated_peak_medium() -> None:
    # Construct so the middle peak lands in the medium band (idx 4–7).
    # max=10 → ratios [1.0, 0, 0.4, 0] → idx [16, 0, 6, 0].
    top, bot = _r.sparkline([10, 0, 4, 0])
    s_bot = strip_ansi(bot)
    # i=2 is an isolated peak at idx=6 → rise medium.
    # i=3 falls from prev idx=6 → fall medium.
    assert s_bot[2] == constants.SPARK_RISE_MED
    assert s_bot[3] == constants.SPARK_FALL_MED


def test_sparkline_isolated_peak_small() -> None:
    # max=10 → ratios [1.0, .1, 0] → idx [16, 1, 0]. Middle cell is a small peak.
    top, bot = _r.sparkline([10, 0, 1, 0])
    s_bot = strip_ansi(bot)
    assert s_bot[2] == constants.SPARK_RISE_SMALL
    assert s_bot[3] == constants.SPARK_FALL_SMALL


def test_sparkline_full_peak_uses_top_row() -> None:
    # max=100; isolated full-height peak. Rise on peak cell, fall on next cell,
    # spanning both rows.
    top, bot = _r.sparkline([0, 100, 0])
    s_top = strip_ansi(top)
    s_bot = strip_ansi(bot)
    assert s_top[0] == ' '
    assert s_top[1] == constants.SPARK_RISE_TOP
    assert s_top[2] == constants.SPARK_FALL_TOP
    assert s_bot[1] == constants.SPARK_RISE_TALL
    assert s_bot[2] == constants.SPARK_FALL_TALL


def test_sparkline_monotone_rise() -> None:
    # Strictly rising — every cell is a rise char (prev < current).
    top, bot = _r.sparkline([1, 2, 3])
    s_bot = strip_ansi(bot)
    # max=3 → ratios [.33, .67, 1.0] → idx [5, 10, 16].
    assert s_bot[0] == constants.SPARK_RISE_MED   # idx=5,  prev=0
    assert s_bot[1] == constants.SPARK_RISE_TALL  # idx=10, prev=5
    assert s_bot[2] == constants.SPARK_RISE_TALL  # idx=16, prev=10


def test_sparkline_monotone_fall() -> None:
    # Strictly falling — first cell rises into the peak, the rest fall using
    # the previous cell's height (the peak we're falling from).
    top, bot = _r.sparkline([3, 2, 1])
    s_bot = strip_ansi(bot)
    # max=3 → idx [16, 10, 5].
    assert s_bot[0] == constants.SPARK_RISE_TALL  # idx=16, prev=0
    assert s_bot[1] == constants.SPARK_FALL_TALL  # prev=16 > idx=10
    assert s_bot[2] == constants.SPARK_FALL_TALL  # prev=10 > idx=5


def test_sparkline_width_matches_input() -> None:
    # One visible cell per data point regardless of slope decoration.
    history = [0, 1, 0, 5, 2, 0, 9, 9, 0]
    top, bot = _r.sparkline(history)
    assert len(strip_ansi(top)) == len(history)
    assert len(strip_ansi(bot)) == len(history)


# live flag tests

_RGB_RE = re.compile(r'\033\[38;2;(\d+);(\d+);(\d+)m')


def _last_rgb(row: str) -> tuple[int, int, int]:
    """Return the RGB triple from the last ANSI colour escape in row."""
    matches = _RGB_RE.findall(row)
    assert matches, f'No RGB escape found in {row!r}'
    r, g, b = matches[-1]
    return int(r), int(g), int(b)


def _prefix_rgb_list(row: str, n_drop: int) -> list[tuple[int, int, int]]:
    """Return all but the last n_drop RGB triples from row."""
    matches = _RGB_RE.findall(row)
    return [(int(r), int(g), int(b)) for r, g, b in matches[:-n_drop]]


def test_sparkline_live_false_identical_to_default() -> None:
    """live=False must produce byte-identical output to no live arg."""
    assert _r.sparkline([1, 2, 3, 4]) == _r.sparkline([1, 2, 3, 4], live=False)


def test_sparkline_live_true_dims_last_cell() -> None:
    """live=True dims each RGB component of the last cell by int(C * 0.5)."""
    top_live, bot_live   = _r.sparkline([1, 2, 3, 4], live=True)
    top_norm, bot_norm   = _r.sparkline([1, 2, 3, 4], live=False)

    lr, lg, lb = _last_rgb(top_live)
    nr, ng, nb = _last_rgb(top_norm)
    assert (lr, lg, lb) == (int(nr * 0.5), int(ng * 0.5), int(nb * 0.5))

    lr, lg, lb = _last_rgb(bot_live)
    nr, ng, nb = _last_rgb(bot_norm)
    assert (lr, lg, lb) == (int(nr * 0.5), int(ng * 0.5), int(nb * 0.5))


def test_sparkline_live_true_earlier_cells_unchanged() -> None:
    """live=True must not touch the prefix of cells before the last."""
    top_live, bot_live = _r.sparkline([5, 6, 7, 8], live=True)
    top_norm, bot_norm = _r.sparkline([5, 6, 7, 8], live=False)

    assert _prefix_rgb_list(top_live, 1) == _prefix_rgb_list(top_norm, 1)
    assert _prefix_rgb_list(bot_live, 1) == _prefix_rgb_list(bot_norm, 1)


def test_sparkline_live_true_empty_history() -> None:
    """Empty history with live=True must return ('', '')."""
    assert _r.sparkline([], live=True) == ('', '')


