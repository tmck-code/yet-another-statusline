from typing import Any

import pytest

import yas.renderer as renderer
from yas.constants import ICON_TOK_RATE
from yas.render.text import _visible_width
from helper import strip_ansi

Renderer = renderer.Renderer


BOX_WIDTH = 160


def _call(show_day_stats: bool = True, **over: Any) -> Any:
    r = Renderer()
    kw = dict(
        sess_in=1, sess_cache=0, sess_out=2,
        day_in=3, day_cache=0, day_out=4,
        sess_cost=0.01, day_cost=0.02,
        tok_rate=0, session_id='', box_width=BOX_WIDTH,
        show_day_stats=show_day_stats,
    )
    kw.update(over)
    return r.tokens_cost(**kw)


# Shape: exactly one content line

def test_tokens_cost_returns_one_line() -> None:
    lines, _cols, mark_col, _min = _call()
    assert len(lines) == 1
    assert mark_col == 0  # tick marker removed (D4)


def test_tokens_cost_returns_one_line_session_only() -> None:
    lines, _cols, _mark, _min = _call(show_day_stats=False)
    assert len(lines) == 1


# Divider columns line up with the rendered │ positions

def test_tokens_cost_cols_within_box() -> None:
    _lines, (col1, col2), _mark, _min = _call()
    assert 1 <= col1 < col2 <= BOX_WIDTH - 3


def test_tokens_cost_divider_cols_match_rendered_bars() -> None:
    # col1/col2 are 1-indexed columns assuming content starts at column 3
    # (after the "│ " border lead); string index = col - 3.
    lines, (col1, col2), _mark, _min = _call()
    stripped = strip_ansi(lines[0])
    assert stripped[col1 - 3] == '│'
    assert stripped[col2 - 3] == '│'


def test_tokens_cost_dividers_track_content() -> None:
    # Columns hug their measured content, so larger token/cost magnitudes push
    # both dividers further right than tiny content — they are not pinned to a
    # fixed budget. The reported cols must still match the rendered │ exactly.
    l1, (s_col1, s_col2), _m1, _s1 = _call(
        sess_in=1, sess_cache=0, sess_out=2,
        day_in=3, day_cache=0, day_out=4, sess_cost=0.01, day_cost=0.02,
    )
    l2, (b_col1, b_col2), _m2, _s2 = _call(
        sess_in=128_400, sess_cache=1_245_000, sess_out=47_300,
        day_in=1_904_000, day_cache=18_300_000, day_out=612_500,
        sess_cost=3.27, day_cost=41.88,
    )
    assert b_col1 > s_col1
    assert b_col2 > s_col2
    for line, col1, col2 in ((l1[0], s_col1, s_col2), (l2[0], b_col1, b_col2)):
        stripped = strip_ansi(line)
        assert stripped[col1 - 3] == '│'
        assert stripped[col2 - 3] == '│'


def test_tokens_cost_divider_grows_honestly_past_budget() -> None:
    # Once content exceeds the realistic-widest budget, the cell grows to hold it
    # so the divider never overflows — the │ shifts right rather than detaching.
    # The reported col must still match the rendered │ exactly.
    lines, (col1, col2), _m, _s = _call(
        sess_in=128_400, sess_cache=1_245_000, sess_out=47_300,
        day_in=1_904_000, day_cache=18_300_000, day_out=612_500,
        sess_cost=327.0, day_cost=4188.88,  # cost '$ $327.00 / $4,188.88' = 21 cols > 20 budget
    )
    stripped = strip_ansi(lines[0])
    assert stripped[col1 - 3] == '│'
    assert stripped[col2 - 3] == '│'


def test_tokens_cost_dividers_differ_across_day_stats_toggle() -> None:
    # Columns hug content, so the merged session/day content (on) is wider than
    # the session-only content (off); the dividers now differ between the two.
    # Each render still keeps its │ at its reported cols.
    l_on,  (on_col1, on_col2),  _m1, _s1 = _call(show_day_stats=True)
    l_off, (off_col1, off_col2), _m2, _s2 = _call(show_day_stats=False)
    assert (on_col1, on_col2) != (off_col1, off_col2)
    for line, col1, col2 in ((l_on[0], on_col1, on_col2), (l_off[0], off_col1, off_col2)):
        stripped = strip_ansi(line)
        assert stripped[col1 - 3] == '│'
        assert stripped[col2 - 3] == '│'


def test_tokens_cost_columns_hug_content() -> None:
    # The column hugs its content: the only gap before the divider is the vsep's
    # 2-space lead — there is no extra pad past the content. Verify the rendered │
    # matches the reported col, the two chars before it are the vsep lead spaces,
    # and the char before THAT is a non-space content char.
    lines, (col1, _col2), _mark, _min = _call(
        sess_in=128_400, sess_cache=1_245_000, sess_out=47_300,
        day_in=1_904_000, day_cache=18_300_000, day_out=612_500,
        sess_cost=3.27, day_cost=41.88,
    )
    stripped = strip_ansi(lines[0])
    assert stripped[col1 - 3] == '│'
    # The two cols immediately before the divider are the vsep's 2-space lead.
    assert stripped[col1 - 5:col1 - 3] == '  '
    # The char before the vsep lead is content, not pad — the column is not
    # padded out past its measured content.
    assert stripped[col1 - 6] != ' '


def test_tokens_cost_rate_icon_after_second_divider() -> None:
    lines, (_col1, col2), _mark, _min = _call()
    stripped = strip_ansi(lines[0])
    # The rate-and-sparkline column begins just past the vsep_leader │.
    assert ICON_TOK_RATE in stripped[col2 - 3:]


# Merged session/day content (day stats on)

def test_tokens_cost_merged_session_day_content() -> None:
    lines, _cols, _mark, _min = _call(
        sess_in=128_400, sess_cache=1_245_000, sess_out=47_300,
        day_in=1_904_000, day_cache=18_300_000, day_out=612_500,
        sess_cost=3.27, day_cost=41.88,
    )
    s = strip_ansi(lines[0])
    assert '↓ 128.4K/1.9M (1.2M/18.3M) ↑ 47.3K/612.5K' in s
    assert '$3.27 / $41.88' in s


# Session-only content (day stats off)

def test_tokens_cost_session_only_content() -> None:
    lines, _cols, _mark, _min = _call(
        show_day_stats=False,
        sess_in=128_400, sess_cache=1_245_000, sess_out=47_300,
        day_in=1_904_000, day_cache=18_300_000, day_out=612_500,
        sess_cost=3.27, day_cost=41.88,
    )
    s = strip_ansi(lines[0])
    # Session figures present, justified; no day figure or day cost anywhere.
    assert '128.4K' in s and '(' in s and '47.3K' in s
    assert '$3.27' in s
    assert '1.9M' not in s
    assert '18.3M' not in s
    assert '612.5K' not in s
    assert '41.88' not in s
    assert '/' not in s.split('t/m')[0]  # no slash-merge before the rate label


# Narrow-box regime (the 80-84 overflow / detached-divider bug). The wide layout
# owns box >= 80, but the three-segment row only genuinely fits around box 85.
# At every box width the rendered row must (i) not overflow the box and (ii) keep
# its two │ aligned with the reported divider cols.

# Realistic widest 6-7 digit magnitudes (the bug-report content).
_NARROW = dict(
    sess_in=155_800, sess_cache=1_600_000, sess_out=18_000,
    day_in=8_400_000, day_cache=216_600_000, day_out=1_500_000,
    sess_cost=6.15, day_cost=560.31, tok_rate=74_600,
)


@pytest.mark.parametrize('box', [85, 86])
def test_tokens_cost_no_overflow_at_or_above_fit_floor(box: int) -> None:
    # At/above its reported min_width the row fits the box exactly. (Below the
    # floor the row physically cannot shrink to its content minimum — that is why
    # build_wide drops it for the compact context line; see test_layout_seam.)
    lines, _cols, _mark, min_w = _call(box_width=box, **_NARROW)
    assert box >= min_w, (box, min_w)  # 85/86 are at/above the floor for this content
    # Content occupies box - 3 cols (2-col '│ ' lead + 1-col trailing '│').
    assert _visible_width(lines[0]) <= box - 3


@pytest.mark.parametrize('box', [80, 82, 84, 85])
def test_tokens_cost_dividers_match_rendered_at_narrow_boxes(box: int) -> None:
    # The assertion that previously only held at box 160: every reported divider
    # column lands on the rendered │ — no detachment from the ┬/┴ elbows.
    lines, (col1, col2), _mark, _min = _call(box_width=box, **_NARROW)
    stripped = strip_ansi(lines[0])
    assert stripped[col1 - 3] == '│'
    assert stripped[col2 - 3] == '│'


def test_tokens_cost_sparkline_omitted_below_10_chars() -> None:
    # The sparkline is dropped when fewer than 10 chars remain for the graph
    # (bar_w < 10); the bare rate label survives. At a small box the leader
    # collapses to its label_w+1 floor (16) and with a tiny rate label bar_w is
    # 9, so the leader region after the 2nd divider is exactly the rate label
    # width. At a wide box bar_w >= 10, so the leader region is wider (graph
    # space present). Width-based so it doesn't depend on the on-disk rate log.
    r = Renderer()
    from yas.constants import ICON_TOK_RATE as _ICON
    from yas.render.text import fmt_tok
    rate_label_w = _visible_width(
        f'{r.TOK_ICON}{_ICON} {r.TOK}{fmt_tok(0)}{r.R}{r.LABEL} t/m{r.R}'
    )

    def leader_region_w(box: int) -> int:
        lines, (_c1, col2), _m, _s = _call(box_width=box)
        s = strip_ansi(lines[0])
        # vsep_block(leader=True) renders the divider then a single trailing
        # space; the leader text begins two columns past the │.
        return _visible_width(s[col2 - 3 + 2:])

    # Small box: bar_w < 10, sparkline omitted -> leader is just the bare label.
    assert leader_region_w(60) == rate_label_w
    # Wide box: bar_w >= 10, graph space present -> leader region is wider.
    assert leader_region_w(BOX_WIDTH) > rate_label_w
    # The rate label / icon stays present in both regimes.
    assert ICON_TOK_RATE in strip_ansi(_call(box_width=60)[0][0])


def test_tokens_cost_min_width_is_consistent_with_fit() -> None:
    # The reported min_width must be the exact smallest box at which the row fits
    # without overflow, so the builder's guard never under- or over-shows the row.
    for box in range(78, 92):
        lines, _cols, _mark, min_w = _call(box_width=box, **_NARROW)
        fits = _visible_width(lines[0]) <= box - 3
        assert fits == (box >= min_w), (box, min_w, _visible_width(lines[0]))
