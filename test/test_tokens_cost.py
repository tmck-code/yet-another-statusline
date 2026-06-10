from typing import Any

import yas.renderer as renderer
from yas.constants import ICON_TOK_RATE
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
    lines, _cols, mark_col = _call()
    assert len(lines) == 1
    assert mark_col == 0  # tick marker removed (D4)


def test_tokens_cost_returns_one_line_session_only() -> None:
    lines, _cols, _mark = _call(show_day_stats=False)
    assert len(lines) == 1


# Divider columns line up with the rendered │ positions

def test_tokens_cost_cols_within_box() -> None:
    _lines, (col1, col2), _mark = _call()
    assert 1 <= col1 < col2 <= BOX_WIDTH - 3


def test_tokens_cost_divider_cols_match_rendered_bars() -> None:
    # col1/col2 are 1-indexed columns assuming content starts at column 3
    # (after the "│ " border lead); string index = col - 3.
    lines, (col1, col2), _mark = _call()
    stripped = strip_ansi(lines[0])
    assert stripped[col1 - 3] == '│'
    assert stripped[col2 - 3] == '│'


def test_tokens_cost_dividers_static_across_magnitudes() -> None:
    # The whole point of static columns: the │ positions must not move as the
    # token and cost magnitudes grow. Tiny vs huge content → identical cols.
    _l1, small, _m1 = _call(
        sess_in=1, sess_cache=0, sess_out=2,
        day_in=3, day_cache=0, day_out=4, sess_cost=0.01, day_cost=0.02,
    )
    _l2, big, _m2 = _call(
        sess_in=128_400, sess_cache=1_245_000, sess_out=47_300,
        day_in=1_904_000, day_cache=18_300_000, day_out=612_500,
        sess_cost=327.0, day_cost=4188.88,
    )
    assert small == big


def test_tokens_cost_dividers_static_across_day_stats_toggle() -> None:
    # The fixed columns depend only on box_width, so the /day toggle never moves
    # the dividers either.
    _l1, on, _m1  = _call(show_day_stats=True)
    _l2, off, _m2 = _call(show_day_stats=False)
    assert on == off


def test_tokens_cost_columns_left_justified_to_fixed_width() -> None:
    # Small content is padded out so the divider lands at the fixed column;
    # verify the rendered │ still matches the reported cols (padding via ANSI),
    # and that the gap before the divider really is pad space (proves the column
    # is left-justified to a fixed width, not measured from the content).
    lines, (col1, col2), _mark = _call()  # tiny values → short tokens content
    stripped = strip_ansi(lines[0])
    assert stripped[col1 - 3] == '│'
    assert stripped[col2 - 3] == '│'
    # The 10 columns immediately before col1's divider lead are all pad spaces.
    assert stripped[col1 - 13:col1 - 3] == ' ' * 10


def test_tokens_cost_rate_icon_after_second_divider() -> None:
    lines, (_col1, col2), _mark = _call()
    stripped = strip_ansi(lines[0])
    # The rate-and-sparkline column begins just past the vsep_leader │.
    assert ICON_TOK_RATE in stripped[col2 - 3:]


# Merged session/day content (day stats on)

def test_tokens_cost_merged_session_day_content() -> None:
    lines, _cols, _mark = _call(
        sess_in=128_400, sess_cache=1_245_000, sess_out=47_300,
        day_in=1_904_000, day_cache=18_300_000, day_out=612_500,
        sess_cost=3.27, day_cost=41.88,
    )
    s = strip_ansi(lines[0])
    assert '↓ 128.4K/1.9M (1.2M/18.3M) ↑ 47.3K/612.5K' in s
    assert '$3.27 / $41.88' in s


# Session-only content (day stats off)

def test_tokens_cost_session_only_content() -> None:
    lines, _cols, _mark = _call(
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
