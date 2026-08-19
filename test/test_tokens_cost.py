from typing import Any

import pytest

import yas.renderer as renderer
from yas.constants import GLYPH_LINES_CHANGED, GLYPH_LINES_READ, ICON_COST
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
        trailing_content='', session_id='', box_width=BOX_WIDTH,
        show_day_stats=show_day_stats, justify=justify,
    )
    kw.update(over)
    return r.tokens_cost(**kw)


# Shape: exactly one content line

def test_tokens_cost_returns_one_line() -> None:
    lines, _cols, mark_col, _min, _has_lines = _call()
    assert len(lines) == 1
    assert mark_col == 0  # tick marker removed (D4)


def test_tokens_cost_returns_one_line_session_only() -> None:
    lines, _cols, _mark, _min, _has_lines = _call(show_day_stats=False)
    assert len(lines) == 1


# Shape: the "skills + plugins" trailing column always gets a divider once the
# box has room -- even with no trailing content, unlike the shed-when-too-
# narrow case below. Default box (160) is wide enough for tokens|cost plus
# the (empty) trailing column: a 2-tuple.

def test_tokens_cost_empty_trailing_content_still_gets_divider() -> None:
    _lines, cols, _mark, _min, _has_lines = _call()
    assert len(cols) == 2


def test_tokens_cost_cols_within_box() -> None:
    _lines, cols, _mark, _min, _has_lines = _call()
    for col in cols:
        assert 1 <= col <= BOX_WIDTH - 3


def test_tokens_cost_divider_cols_match_rendered_bars() -> None:
    # cols are 1-indexed columns assuming content starts at column 3
    # (after the "│ " border lead); string index = col - 3.
    lines, cols, _mark, _min, _has_lines = _call()
    stripped = strip_ansi(lines[0])
    for col in cols:
        assert stripped[col - 3] == '│'


def test_tokens_cost_divider_cols_match_rendered_bars_with_lines_segment() -> None:
    # Sibling of the 2-tuple case above: with the lines segment ALSO included
    # (box wide enough to clear LINES_SEGMENT_MIN_WIDTH), vsep_cols grows to a
    # 3-tuple (tokens|lines, lines|cost, cost|leader) and every reported
    # column must still land on its rendered │.
    lines, cols, _mark, _min, _has_lines = _call(box_width=110, lines=(1234, 567))
    assert len(cols) == 3
    stripped = strip_ansi(lines[0])
    for col in cols:
        assert stripped[col - 3] == '│'


def test_tokens_cost_dividers_track_content() -> None:
    # Columns hug their measured content, so larger token/cost magnitudes push
    # the first (tokens|cost) divider further right than tiny content — it is
    # not pinned to a fixed budget. The reported col must still match the
    # rendered │ exactly.
    l1, s_cols, _m1, _s1, _h1 = _call(
        sess_in=1, sess_cache=0, sess_out=2,
        day_in=3, day_cache=0, day_out=4, sess_cost=0.01, day_cost=0.02,
    )
    l2, b_cols, _m2, _s2, _h2 = _call(
        sess_in=128_400, sess_cache=1_245_000, sess_out=47_300,
        day_in=1_904_000, day_cache=18_300_000, day_out=612_500,
        sess_cost=3.27, day_cost=41.88,
    )
    assert b_cols[0] > s_cols[0]
    for line, cols in ((l1[0], s_cols), (l2[0], b_cols)):
        stripped = strip_ansi(line)
        for col in cols:
            assert stripped[col - 3] == '│'


def test_tokens_cost_divider_grows_honestly_past_budget() -> None:
    # Once content exceeds the realistic-widest budget, the cell grows to hold it
    # so the divider never overflows — the │ shifts right rather than detaching.
    # The reported col must still match the rendered │ exactly.
    lines, cols, _m, _s, _h = _call(
        sess_in=128_400, sess_cache=1_245_000, sess_out=47_300,
        day_in=1_904_000, day_cache=18_300_000, day_out=612_500,
        sess_cost=327.0, day_cost=4188.88,  # cost '$ $327.00 / $4,188.88' = 21 cols > 20 budget
    )
    stripped = strip_ansi(lines[0])
    for col in cols:
        assert stripped[col - 3] == '│'


def test_tokens_cost_dividers_differ_across_day_stats_toggle() -> None:
    # Columns hug content, so the merged session/day content (on) is wider than
    # the session-only content (off); the first divider now differs between the
    # two. Each render still keeps its │ at its reported cols.
    l_on,  on_cols,  _m1, _s1, _h1 = _call(show_day_stats=True)
    l_off, off_cols, _m2, _s2, _h2 = _call(show_day_stats=False)
    assert on_cols[0] != off_cols[0]
    for line, cols in ((l_on[0], on_cols), (l_off[0], off_cols)):
        stripped = strip_ansi(line)
        for col in cols:
            assert stripped[col - 3] == '│'


def test_tokens_cost_columns_hug_content() -> None:
    # The column hugs its content: the only gap before the divider is the vsep's
    # 2-space lead — there is no extra pad past the content. Verify the rendered │
    # matches the reported col, the two chars before it are the vsep lead spaces,
    # and the char before THAT is a non-space content char.
    lines, (col1, *_rest), _mark, _min, _has_lines = _call(
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


# Trailing content column (e.g. "skills + plugins")

def test_tokens_cost_trailing_content_appears_after_divider() -> None:
    lines, cols, _mark, _min, _has_lines = _call(trailing_content='hello')
    stripped = strip_ansi(lines[0])
    assert len(cols) == 2
    assert 'hello' in stripped[cols[-1] - 3:]


def test_tokens_cost_trailing_column_present_and_blank_when_content_empty() -> None:
    # The "skills + plugins" section is shown (divider + blank padding) even
    # with nothing to display -- its border must not depend on content.
    with_empty = _call(trailing_content='')
    lines, cols, _mark, _min, _has_lines = with_empty
    assert len(cols) == 2
    stripped = strip_ansi(lines[0])
    assert stripped[cols[-1] - 2:].strip() == ''


def test_tokens_cost_trailing_content_dropped_when_too_narrow() -> None:
    # A long trailing string can't fit at a tight box; the segment (and its
    # divider) is shed and the row falls back to the tokens|cost shape.
    lines, cols, _mark, _min, _has_lines = _call(box_width=90, trailing_content='x' * 200)
    assert len(cols) == 1
    assert 'x' * 200 not in strip_ansi(lines[0])


def test_tokens_cost_trailing_content_padded_to_column_width() -> None:
    # A short trailing string is left-justified and padded with spaces out to
    # the leader column's width, not truncated or centred.
    lines, cols, _mark, _min, _has_lines = _call(trailing_content='hi')
    stripped = strip_ansi(lines[0])
    # vsep_block(leader=True) renders the divider then a single trailing
    # space; the leader text begins two columns past the │.
    leader_region = stripped[cols[-1] - 3 + 2:]
    assert leader_region.startswith('hi')


# Merged session/day content (day stats on)

def test_tokens_cost_merged_session_day_content() -> None:
    lines, _cols, _mark, _min, _has_lines = _call(
        sess_in=128_400, sess_cache=1_245_000, sess_out=47_300,
        day_in=1_904_000, day_cache=18_300_000, day_out=612_500,
        sess_cost=3.27, day_cost=41.88,
    )
    s = strip_ansi(lines[0])
    assert '↓ 128.4K/1.9M (1.2M/18.3M) ↑ 47.3K/612.5K' in s
    assert '$3.27 / $41.88' in s


# Session-only content (day stats off)

def test_tokens_cost_session_only_content() -> None:
    lines, _cols, _mark, _min, _has_lines = _call(
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


# Narrow-box regime (the 80-84 overflow / detached-divider bug). The wide layout
# owns box >= 80, but the row's own content grows the floor with realistic
# magnitudes. At every box width the rendered row must (i) not overflow the box
# and (ii) keep its │ aligned with the reported divider col.

# Realistic widest 6-7 digit magnitudes (the bug-report content).
_NARROW = dict(
    sess_in=155_800, sess_cache=1_600_000, sess_out=18_000,
    day_in=8_400_000, day_cache=216_600_000, day_out=1_500_000,
    sess_cost=6.15, day_cost=560.31,
)


def test_tokens_cost_no_overflow_at_or_above_fit_floor() -> None:
    # At/above its reported min_width the row fits the box exactly. (Below the
    # floor the row physically cannot shrink to its content minimum — that is why
    # build_wide drops it for the compact context line; see test_layout_seam.)
    floor = _call(box_width=BOX_WIDTH, **_NARROW)[3]
    for box in (floor, floor + 1, floor + 5):
        lines, _cols, _mark, min_w, _has_lines = _call(box_width=box, **_NARROW)
        assert box >= min_w, (box, min_w)
        # Content occupies box - 3 cols (2-col '│ ' lead + 1-col trailing '│').
        assert _visible_width(lines[0]) <= box - 3


@pytest.mark.parametrize('box', [78, 80, 85, 90])
def test_tokens_cost_dividers_match_rendered_at_narrow_boxes(box: int) -> None:
    # Every reported divider column lands on the rendered │ — no detachment
    # from the ┬/┴ elbows. The (empty) trailing "skills + plugins" divider
    # still fits at these widths, so the shape is a 2-tuple (tokens|cost,
    # cost|leader).
    lines, cols, _mark, _min, _has_lines = _call(box_width=box, **_NARROW)
    stripped = strip_ansi(lines[0])
    assert len(cols) == 2
    for col in cols:
        assert stripped[col - 3] == '│'


@pytest.mark.parametrize('box', [103, 110, 130, 160])
def test_tokens_cost_dividers_match_rendered_at_wide_boxes_with_lines(box: int) -> None:
    # Sibling of the narrow-box divider check above, for the 3-tuple shape:
    # every reported divider column lands on the rendered │ once both the
    # lines segment and the trailing "skills + plugins" divider are in play.
    lines, cols, _mark, _min, _has_lines = _call(box_width=box, lines=(1234, 567), **_NARROW)
    assert len(cols) == 3
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
    # renders: vsep_cols grows to a 3-tuple (tokens|lines, lines|cost,
    # cost|leader) and the glyphs/values appear.
    lines, cols, _mark, _min, _has_lines = _call(box_width=110, lines=(1234, 567))
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


def test_tokens_cost_min_width_unaffected_by_trailing_content() -> None:
    # The trailing content column never affects the returned min_width — it is
    # derived from the protected tokens-sess/day survivor alone.
    for box in (60, 95, 160):
        min_without = _call(box_width=box)[3]
        min_with = _call(box_width=box, trailing_content='skills + plugins')[3]
        assert min_with == min_without


# Justify breathing room (day stats on). Slack that would otherwise flow
# past the content is first spent as padding *inside* the sections.

# Content with realistic magnitudes so the gaps/pads are visible in the strip.
_JUSTIFY = dict(
    sess_in=17_900, sess_cache=34_600, sess_out=258,
    day_in=872_000, day_cache=33_000_000, day_out=306_100,
    sess_cost=0.39, day_cost=85.48,
)


def test_tokens_cost_justify_off_unchanged() -> None:
    # justify defaults to off; passing justify=False explicitly must be
    # byte-for-byte identical to the default call.
    a_lines, a_cols, a_mark, a_min, a_h = _call(**_JUSTIFY)
    b_lines, b_cols, b_mark, b_min, b_h = _call(justify=False, **_JUSTIFY)
    assert (a_lines, a_cols, a_mark, a_min, a_h) == (b_lines, b_cols, b_mark, b_min, b_h)


def test_tokens_cost_justify_widens_gaps_and_pads_to_cap() -> None:
    # At a wide box with plenty of slack, justify fills every slot to the 4-space
    # cap: the two tokens inter-group gaps become 4, and the cost LHS/RHS each
    # get 4 spaces.
    on,  _c_on,  _m_on,  _s_on, _h_on  = _call(box_width=160, justify=True,  **_JUSTIFY)
    off, _c_off, _m_off, _s_off, _h_off = _call(box_width=160, justify=False, **_JUSTIFY)
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


def test_tokens_cost_justify_dividers_match_rendered_bars() -> None:
    # The padding shifts the dividers; each must still land exactly on the
    # rendered │ so the ┬/┴ elbows above/below stay attached.
    lines, cols, _mark, _min, _has_lines = _call(box_width=160, justify=True, **_JUSTIFY)
    stripped = strip_ansi(lines[0])
    for col in cols:
        assert stripped[col - 3] == '│'


def test_tokens_cost_justify_min_width_unchanged() -> None:
    # The optional padding must not inflate min_width: the reported floor is
    # identical with justify on and off, and at that floor the row fits exactly.
    for box in range(78, 92):
        _l_on,  _c_on,  _m_on,  min_on, _h_on  = _call(box_width=box, justify=True,  **_NARROW)
        _l_off, _c_off, _m_off, min_off, _h_off = _call(box_width=box, justify=False, **_NARROW)
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
        lines, _cols, _mark, min_w, _has_lines = _call(box_width=box, **_NARROW)
        fits = _visible_width(lines[0]) <= box - 3
        assert fits == (box >= min_w), (box, min_w, _visible_width(lines[0]))


# show_icons: default on preserves current behaviour; off drops every
# per-number glyph in the row but keeps the numbers and dividers intact.

def test_tokens_cost_show_icons_defaults_true() -> None:
    on  = _call()
    default = _call(show_icons=True)
    assert on == default


def test_tokens_cost_show_icons_false_drops_glyphs() -> None:
    lines, _cols, _mark, _min, _has_lines = _call(show_icons=False, lines=(1234, 567), box_width=140)
    text = lines[0]
    for glyph in (ICON_COST, GLYPH_LINES_READ, GLYPH_LINES_CHANGED):
        assert glyph not in text


def test_tokens_cost_show_icons_true_keeps_glyphs() -> None:
    lines, _cols, _mark, _min, _has_lines = _call(show_icons=True, lines=(1234, 567), box_width=140)
    text = lines[0]
    for glyph in (ICON_COST, GLYPH_LINES_READ, GLYPH_LINES_CHANGED):
        assert glyph in text


def test_tokens_cost_has_lines_flag_true_when_segment_survives() -> None:
    # Regression: `has_lines` must reflect the segment's actual inclusion in
    # the returned line, not whether its (show_icons-gated) read glyph
    # happens to be present -- the caller (layout.py) anchors the 'loc r/w'
    # and 'cost sess/day' labels off this flag, not off glyph-sniffing.
    _lines, _cols, _mark, _min, has_lines = _call(box_width=110, lines=(1234, 567))
    assert has_lines is True


def test_tokens_cost_has_lines_flag_true_with_icons_off() -> None:
    # The bug this guards: with show_icons=False the read-lines glyph never
    # appears in the rendered row even though the segment itself is present
    # -- `has_lines` must still report True (it comes from the shed-ladder
    # decision, not the rendered glyph).
    lines, _cols, _mark, _min, has_lines = _call(show_icons=False, lines=(1234, 567), box_width=140)
    assert has_lines is True
    assert GLYPH_LINES_READ not in lines[0]  # glyph absent, segment still present


def test_tokens_cost_has_lines_flag_false_when_shed() -> None:
    # Below LINES_SEGMENT_MIN_WIDTH the segment is shed even though `lines=`
    # was passed -- `has_lines` must report False so the caller doesn't try
    # to anchor a label onto a segment that isn't there.
    _lines, _cols, _mark, _min, has_lines = _call(box_width=95, lines=(1234, 567))
    assert has_lines is False


def test_tokens_cost_has_lines_flag_false_without_lines_arg() -> None:
    _lines, _cols, _mark, _min, has_lines = _call()
    assert has_lines is False


def test_tokens_cost_show_icons_false_keeps_numbers_and_dividers() -> None:
    lines, cols, _mark, _min, _has_lines = _call(show_icons=False, box_width=BOX_WIDTH)
    stripped = strip_ansi(lines[0])
    for col in cols:
        assert stripped[col - 3] == '│'
    assert '0.01' in stripped and '0.02' in stripped


def test_tokens_cost_show_icons_false_narrower_min_width() -> None:
    # Fewer glyphs means less content, so the row's own min_width floor with
    # icons off must not exceed the icons-on floor.
    _l_on,  _c_on,  _m_on,  min_on,  _h_on  = _call(show_icons=True,  **_NARROW)
    _l_off, _c_off, _m_off, min_off, _h_off = _call(show_icons=False, **_NARROW)
    assert min_off <= min_on


def test_tokens_cost_show_icons_false_session_only_drops_cost_icon() -> None:
    lines, _cols, _mark, _min, _has_lines = _call(show_icons=False, show_day_stats=False)
    text = lines[0]
    assert ICON_COST not in text


# show_icons=False, show_day_stats=True: with no icon to reserve the row's
# left margin, `sess_in` (the leading number) is right-justified to `IN_W`
# instead. Two things this must guarantee: (1) the reserved width matches
# row 2's context-fill number (also rjust'd, in `context_line`) so the two
# rows' leading digits share the same right edge -- regardless of how many
# digits either value currently has; (2) growing `sess_in` past a realistic
# "everyday" width (e.g. 25.9K -> 123.0K) doesn't ripple into the columns
# after it or land the number flush against the row's own left border.

def test_tokens_cost_show_icons_false_leading_number_right_justified() -> None:
    lines, _cols, _mark, _min, _has_lines = _call(show_icons=False, sess_in=1)
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
    on_default = _call(show_icons=True, sess_in=1)
    on_explicit = _call(show_icons=True, sess_in=1)
    assert on_default == on_explicit
