from typing import Any

import pytest

import yas.renderer as renderer
from yas.constants import GLYPH_LINES_CHANGED, GLYPH_LINES_READ, ICON_COST, ICON_TOK_RATE
from yas.render.text import _visible_width
from helper import strip_ansi

Renderer = renderer.Renderer


BOX_WIDTH = 160


def _call(show_day_stats: bool = True, justify: bool = False, **over: Any) -> Any:
    r = Renderer()
    kw = dict(
        sess_in=1, sess_cache=0, sess_out=2,
        day_in=3, day_cache=0, day_out=4,
        sess_cost=0.01, day_cost=0.02,
        tok_rate=0, session_id='', box_width=BOX_WIDTH,
        show_day_stats=show_day_stats, justify=justify,
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


def test_tokens_cost_divider_cols_match_rendered_bars_with_lines_segment() -> None:
    # Sibling of the 2-tuple case above: with the lines segment included (box
    # wide enough to clear LINES_SEGMENT_MIN_WIDTH), vsep_cols is a 3-tuple and
    # every reported column must still land on its rendered │.
    lines, cols, _mark, _min = _call(box_width=110, lines=(1234, 567))
    assert len(cols) == 3
    stripped = strip_ansi(lines[0])
    for col in cols:
        assert stripped[col - 3] == '│'


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
    # box=80 is now narrow enough that the shed ladder drops the
    # tokens-over-time (rate/sparkline) segment entirely -- one divider
    # survives (tokens|cost) instead of two (tokens|cost|leader).
    lines, cols, _mark, _min = _call(box_width=box, **_NARROW)
    stripped = strip_ansi(lines[0])
    if box == 80:
        assert len(cols) == 1
    else:
        assert len(cols) == 2
    for col in cols:
        assert stripped[col - 3] == '│'


@pytest.mark.parametrize('box', [103, 110, 130, 160])
def test_tokens_cost_dividers_match_rendered_at_wide_boxes_with_lines(box: int) -> None:
    # Sibling of the narrow-box divider check above, for the 3-tuple shape:
    # every reported divider column (2 or 3, box-dependent) lands on the
    # rendered │ once the lines segment is in play.
    lines, cols, _mark, _min = _call(box_width=box, lines=(1234, 567), **_NARROW)
    stripped = strip_ansi(lines[0])
    for col in cols:
        assert stripped[col - 3] == '│'


# Lines segment shed / present, straddling LINES_SEGMENT_MIN_WIDTH (103)

def test_tokens_cost_lines_segment_shed_below_103_is_byte_identical() -> None:
    # Below 103 cols the segment sheds even though `lines=` was passed, and the
    # rendered row + min_width are byte-identical to a call with no `lines=` at
    # all — proving zero regression in the 85-102 band (Decision 8).
    with_lines = _call(box_width=95, lines=(1234, 567))
    without_lines = _call(box_width=95)
    assert with_lines == without_lines
    assert len(with_lines[1]) == 2


def test_tokens_cost_lines_segment_present_at_or_above_103() -> None:
    # At a box wide enough to clear LINES_SEGMENT_MIN_WIDTH, the segment
    # renders: vsep_cols grows to a 3-tuple and the glyphs/values appear.
    lines, cols, _mark, _min = _call(box_width=110, lines=(1234, 567))
    assert len(cols) == 3
    s = strip_ansi(lines[0])
    assert GLYPH_LINES_READ in s
    assert GLYPH_LINES_CHANGED in s
    assert '1.2K' in s or '1,234' in s  # fmt_tok humanises 1234
    assert '567' in s


def test_tokens_cost_min_width_unchanged_when_lines_shed() -> None:
    # When the segment is shed (box_width below the with-segment floor and/or
    # below 103), the returned min_width must never rise above the pre-change
    # (no-lines) value.
    for box in (60, 95, 102):
        min_without = _call(box_width=box)[3]
        min_with = _call(box_width=box, lines=(1234, 567))[3]
        assert min_with == min_without


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
        f'{r.TOK_ICON}{_ICON}  {r.TOK}{fmt_tok(0)}{r.R}{r.LABEL} t/m{r.R}'
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


def test_tokens_cost_sparkline_omitted_below_10_chars_with_lines_segment() -> None:
    # The sparkline-degrade behaviour above holds unchanged when the lines
    # segment is present: bar_w < 10 still collapses the leader to the bare
    # rate label, and the 3rd divider (lines segment) is still reported and
    # matches its rendered │.
    r = Renderer()
    rate_label_w = _visible_width(
        f'{r.TOK_ICON}{ICON_TOK_RATE}  {r.TOK}{"74.6K"}{r.R}{r.LABEL} t/m{r.R}'
    )

    def leader_region_w(box: int) -> int:
        lines, cols, _m, _s = _call(box_width=box, lines=(1234, 567), **_NARROW)
        col2 = cols[-1]
        s = strip_ansi(lines[0])
        return _visible_width(s[col2 - 3 + 2:])

    # Narrow-but-lines-included box: bar_w < 10 -> bare label, same width as
    # a rate label built from tok_rate=74_600 (matches _NARROW's tok_rate).
    lines_narrow, cols_narrow, _m, _s = _call(box_width=103, lines=(1234, 567), **_NARROW)
    assert len(cols_narrow) == 3
    assert leader_region_w(103) == rate_label_w
    stripped_narrow = strip_ansi(lines_narrow[0])
    for col in cols_narrow:
        assert stripped_narrow[col - 3] == '│'
    # Wide box: bar_w >= 10, graph space present -> leader region is wider.
    assert leader_region_w(160) > rate_label_w


# Justify breathing room (day stats on). Slack that would all feed the sparkline
# is first spent as padding *inside* the sections, each capped at 4 spaces.

# Content with realistic magnitudes so the gaps/pads are visible in the strip.
_JUSTIFY = dict(
    sess_in=17_900, sess_cache=34_600, sess_out=258,
    day_in=872_000, day_cache=33_000_000, day_out=306_100,
    sess_cost=0.39, day_cost=85.48, tok_rate=18_100,
)


def test_tokens_cost_justify_off_unchanged() -> None:
    # justify defaults to off; passing justify=False explicitly must be
    # byte-for-byte identical to the default call.
    a_lines, a_cols, a_mark, a_min = _call(**_JUSTIFY)
    b_lines, b_cols, b_mark, b_min = _call(justify=False, **_JUSTIFY)
    assert (a_lines, a_cols, a_mark, a_min) == (b_lines, b_cols, b_mark, b_min)


def test_tokens_cost_justify_widens_gaps_and_pads_to_cap() -> None:
    # At a wide box with plenty of slack, justify fills every slot to the 4-space
    # cap: the two tokens inter-group gaps become 4, and the cost LHS/RHS and the
    # t/m leader LHS each get 4 spaces.
    on,  _c_on,  _m_on,  _s_on  = _call(box_width=160, justify=True,  **_JUSTIFY)
    off, _c_off, _m_off, _s_off = _call(box_width=160, justify=False, **_JUSTIFY)
    s_on  = strip_ansi(on[0])
    s_off = strip_ansi(off[0])

    # Inter-group gaps widen from 1 to the 4-space cap.
    assert '/872.0K    (34.6K/33.0M)    ↑ 258/306.1K' in s_on
    assert '/872.0K (34.6K/33.0M) ↑ 258/306.1K' in s_off

    # Cost section gains 4 spaces of LHS padding. The vsep renders as '  │ '
    # (2-col lead, divider, 1 trailing space), so the LHS cap shows as the 1
    # vsep-trail space + 4 pad = 5 spaces between the divider and the cost icon.
    i = s_on.index(ICON_COST)             # ICON_COST starts the cost cell
    assert s_on[i - 6:i] == '│' + ' ' * 5  # divider + 1 vsep trail + 4-space LHS cap
    assert '$85.48    ' in s_on           # 4-space RHS cap trails the day cost
    # t/m leader gains 4 spaces of LHS padding (again behind the 1 vsep-trail space).
    j = s_on.index(ICON_TOK_RATE)         # ICON_TOK_RATE leads the rate label
    assert s_on[j - 6:j] == '│' + ' ' * 5  # divider + 1 vsep trail + 4-space leader cap


def test_tokens_cost_justify_dividers_match_rendered_bars() -> None:
    # The padding shifts col1/col2; both must still land exactly on the rendered
    # │ so the ┬/┴ elbows above/below stay attached.
    lines, (col1, col2), _mark, _min = _call(box_width=160, justify=True, **_JUSTIFY)
    stripped = strip_ansi(lines[0])
    assert stripped[col1 - 3] == '│'
    assert stripped[col2 - 3] == '│'


def test_tokens_cost_justify_min_width_unchanged() -> None:
    # The optional padding must not inflate min_width: the reported floor is
    # identical with justify on and off, and at that floor the row fits exactly.
    for box in range(78, 92):
        _l_on,  _c_on,  _m_on,  min_on  = _call(box_width=box, justify=True,  **_NARROW)
        _l_off, _c_off, _m_off, min_off = _call(box_width=box, justify=False, **_NARROW)
        assert min_on == min_off
    # At the tight floor the gaps collapse to 1 (no slack), so the justify-on row
    # equals the justify-off row byte-for-byte.
    floor = _call(box_width=160, justify=False, **_NARROW)[3]
    on  = _call(box_width=floor, justify=True,  **_NARROW)
    off = _call(box_width=floor, justify=False, **_NARROW)
    assert on == off


def test_tokens_cost_justify_off_for_session_only() -> None:
    # Justify only applies to the show_day_stats branch; with day stats off the
    # row is byte-for-byte identical regardless of the justify flag.
    on  = _call(show_day_stats=False, justify=True,  **_JUSTIFY)
    off = _call(show_day_stats=False, justify=False, **_JUSTIFY)
    assert on == off


def test_tokens_cost_min_width_is_consistent_with_fit() -> None:
    # The reported min_width must be the exact smallest box at which the row fits
    # without overflow, so the builder's guard never under- or over-shows the row.
    for box in range(78, 92):
        lines, _cols, _mark, min_w = _call(box_width=box, **_NARROW)
        fits = _visible_width(lines[0]) <= box - 3
        assert fits == (box >= min_w), (box, min_w, _visible_width(lines[0]))


# show_icons: default on preserves current behaviour; off drops every
# per-number glyph in the row but keeps the numbers and dividers intact.

def test_tokens_cost_show_icons_defaults_true() -> None:
    on  = _call()
    default = _call(show_icons=True)
    assert on == default


def test_tokens_cost_show_icons_false_drops_glyphs() -> None:
    lines, _cols, _mark, _min = _call(show_icons=False, lines=(1234, 567), box_width=140)
    text = lines[0]
    for glyph in (ICON_COST, ICON_TOK_RATE, GLYPH_LINES_READ, GLYPH_LINES_CHANGED):
        assert glyph not in text


def test_tokens_cost_show_icons_true_keeps_glyphs() -> None:
    lines, _cols, _mark, _min = _call(show_icons=True, lines=(1234, 567), box_width=140)
    text = lines[0]
    for glyph in (ICON_COST, ICON_TOK_RATE, GLYPH_LINES_READ, GLYPH_LINES_CHANGED):
        assert glyph in text


def test_tokens_cost_show_icons_false_keeps_numbers_and_dividers() -> None:
    lines, (col1, col2), _mark, _min = _call(show_icons=False, box_width=BOX_WIDTH)
    stripped = strip_ansi(lines[0])
    assert stripped[col1 - 3] == '│'
    assert stripped[col2 - 3] == '│'
    assert '0.01' in stripped and '0.02' in stripped


def test_tokens_cost_show_icons_false_narrower_min_width() -> None:
    # Fewer glyphs means less content, so the row's own min_width floor with
    # icons off must not exceed the icons-on floor.
    _l_on,  _c_on,  _m_on,  min_on  = _call(show_icons=True,  **_NARROW)
    _l_off, _c_off, _m_off, min_off = _call(show_icons=False, **_NARROW)
    assert min_off <= min_on


def test_tokens_cost_show_icons_false_session_only_drops_cost_icon() -> None:
    lines, _cols, _mark, _min = _call(show_icons=False, show_day_stats=False)
    text = lines[0]
    assert ICON_COST not in text
    assert ICON_TOK_RATE not in text


# show_icons=False, show_day_stats=True: with no icon to reserve the row's
# left margin, `sess_in` (the leading number) is right-justified to `IN_W`
# instead. Two things this must guarantee: (1) the reserved width matches
# row 2's context-fill number (also rjust'd, in `context_line`) so the two
# rows' leading digits share the same right edge -- regardless of how many
# digits either value currently has; (2) growing `sess_in` past a realistic
# "everyday" width (e.g. 25.9K -> 123.0K) doesn't ripple into the columns
# after it or land the number flush against the row's own left border.

def test_tokens_cost_show_icons_false_leading_number_right_justified() -> None:
    lines, _cols, _mark, _min = _call(show_icons=False, sess_in=1)
    stripped = strip_ansi(lines[0])
    # Row content starts right after the single border-gap space border_line
    # always inserts; IN_W is the reserved field width for the leading number.
    lead_field = stripped[:Renderer.IN_W]
    assert lead_field.rstrip(' ').endswith('1')
    assert lead_field == '1'.rjust(Renderer.IN_W)


def test_tokens_cost_show_icons_false_leading_number_right_edge_stable_across_magnitude() -> None:
    """The right edge of the reserved `sess_in` field must not move as the
    value grows from a small session-start number up through a realistic
    everyday count -- otherwise every column after it (the cache/day figures,
    the │ dividers, the cost/rate columns) would shift underneath it."""
    small = strip_ansi(_call(show_icons=False, sess_in=1)[0][0])
    big   = strip_ansi(_call(show_icons=False, sess_in=25_900)[0][0])
    huge  = strip_ansi(_call(show_icons=False, sess_in=123_000)[0][0])
    # The char immediately after the reserved field (the day-count '/') sits
    # at the same offset regardless of sess_in's magnitude.
    assert small[Renderer.IN_W] == '/'
    assert big[Renderer.IN_W]   == '/'
    assert huge[Renderer.IN_W]  == '/'


def test_tokens_cost_show_icons_false_leading_number_matches_context_line_margin() -> None:
    """Row 2 (`context_line`) and row 3 (`tokens_cost`) share the same
    reserved-width convention with icons off: both rjust their leading
    number to a fixed width immediately after border_line's own 1-space
    gap, so the two rows' numbers share a stable right edge."""
    from yas.session import ContextWindow

    r = Renderer()
    ctx = ContextWindow(total_input_tokens=16_000, total_output_tokens=0,
                         context_window_size=200_000, used_percentage=8.0)
    ctx_line = strip_ansi(r.context_line(ctx, available=76, show_icons=False))
    tok_line = strip_ansi(_call(show_icons=False, sess_in=16_000)[0][0])
    # Both fields are right-justified to 6 columns from the row's start
    # (border_line's leading space is stripped from both here, since neither
    # string above includes it -- they're raw section content).
    assert ctx_line[:Renderer.IN_W].rstrip(' ')[-1] == tok_line[:Renderer.IN_W].rstrip(' ')[-1]
    assert len(ctx_line[:Renderer.IN_W]) == len(tok_line[:Renderer.IN_W]) == Renderer.IN_W


def test_tokens_cost_show_icons_true_leading_number_unchanged() -> None:
    """With icons on, the icon itself already reserves the margin -- the
    show_icons=False rjust fix must not perturb the icons-on row shape."""
    on_default = _call(sess_in=1)
    on_explicit = _call(show_icons=True, sess_in=1)
    assert on_default == on_explicit
