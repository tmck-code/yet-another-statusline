import statusline_command as sl
from conftest import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer


BOX_WIDTH = 80


def _call():
    r = Renderer()
    return r.tokens_cost(
        sess_in=1, sess_cache=0, sess_out=2,
        day_in=3,  day_cache=0, day_out=4,
        sess_cost=0.01, day_cost=0.02,
        tok_rate=0, session_id='', box_width=BOX_WIDTH,
    )


def test_tokens_cost_returns_two_equal_width_lines():
    lines, cols = _call()
    assert len(lines) == 2
    assert _visible_width(lines[0]) == _visible_width(lines[1])


def test_tokens_cost_cols_within_box():
    lines, cols = _call()
    col1, col2 = cols
    assert 1 <= col1
    assert col1 < col2
    assert col2 <= BOX_WIDTH - 3
