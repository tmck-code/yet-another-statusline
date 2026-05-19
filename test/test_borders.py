import pytest
import statusline_command as sl
from conftest import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer


@pytest.fixture
def r():
    return Renderer()


@pytest.mark.parametrize('w', [10, 40, 55, 80, 130])
def test_border_top_width(r, w):
    assert _visible_width(r.border_top(w)) == w


@pytest.mark.parametrize('w', [10, 40, 55, 80, 130])
def test_border_bottom_width(r, w):
    assert _visible_width(r.border_bottom(w)) == w


@pytest.mark.parametrize('w', [10, 40, 55, 80, 130])
def test_border_separator_width(r, w):
    assert _visible_width(r.border_separator(w)) == w


@pytest.mark.parametrize('w', [10, 40, 55, 80, 130])
def test_border_separator_dim_width(r, w):
    assert _visible_width(r.border_separator_dim(w)) == w


def test_border_top_session_id_truncated(r):
    out = r.border_top(width=20, session_id='a' * 50)
    assert _visible_width(out) == 20
    assert '…' in strip_ansi(out)


def test_border_bottom_ups_markers(r):
    out = r.border_bottom(width=20, ups=(5, 10))
    stripped = strip_ansi(out)
    assert _visible_width(out) == 20
    # ups=(5, 10): column numbers 5 and 10 (1-based) → string indices 4 and 9
    assert stripped[4] == '┴'
    assert stripped[9] == '┴'


def test_border_line_width(r):
    out = r.border_line('hello', width=20)
    assert _visible_width(out) == 20
