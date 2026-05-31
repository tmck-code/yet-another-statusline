import pytest
import statusline.borders as borders
import statusline.gradient as gradient
import statusline.renderer as renderer_mod
from statusline.constants import PILL_LEFT, PILL_RIGHT, PILL_TL, PILL_TR, PILL_BL, PILL_BR
from statusline.pill import Pill
from statusline.text import _visible_width
from helper import strip_ansi

Renderer = renderer_mod.Renderer


@pytest.fixture
def r() -> borders.BorderRenderer:
    g = gradient.GradientEngine()
    return borders.BorderRenderer(g)


@pytest.mark.parametrize('w', [10, 40, 55, 80, 130])
def test_border_top_width(r: borders.BorderRenderer, w: int) -> None:
    assert _visible_width(r.border_top(w)) == w


@pytest.mark.parametrize('w', [10, 40, 55, 80, 130])
def test_border_bottom_width(r: borders.BorderRenderer, w: int) -> None:
    assert _visible_width(r.border_bottom(w)) == w


@pytest.mark.parametrize('w', [10, 40, 55, 80, 130])
def test_border_separator_width(r: borders.BorderRenderer, w: int) -> None:
    assert _visible_width(r.border_separator(w)) == w


@pytest.mark.parametrize('w', [10, 40, 55, 80, 130])
def test_border_separator_dim_width(r: borders.BorderRenderer, w: int) -> None:
    assert _visible_width(r.border_separator_dim(w)) == w


def test_border_top_session_id_truncated(r: borders.BorderRenderer) -> None:
    out = r.border_top(width=20, session_id='a' * 50)
    assert _visible_width(out) == 20
    assert '…' in strip_ansi(out)


def test_border_bottom_ups_markers(r: borders.BorderRenderer) -> None:
    out = r.border_bottom(width=20, ups=(5, 10))
    stripped = strip_ansi(out)
    assert _visible_width(out) == 20
    # ups=(5, 10): column numbers 5 and 10 (1-based) → string indices 4 and 9
    assert stripped[4] == '┴'
    assert stripped[9] == '┴'


def test_border_line_width(r: borders.BorderRenderer) -> None:
    out = r.border_line('hello', width=20)
    assert _visible_width(out) == 20


def test_border_line_right_pill_width(r: borders.BorderRenderer) -> None:
    right_pill = f'{PILL_LEFT}abc{PILL_RIGHT}'
    out = r.border_line('left', width=30, right_pill=right_pill)
    assert _visible_width(out) == 30
    stripped = strip_ansi(out)
    assert stripped.endswith(PILL_RIGHT)
    assert PILL_LEFT in stripped


def test_border_top_right_flush_pill(r: borders.BorderRenderer) -> None:
    pill = Pill(start=21, end=30, anchor=(120, 80, 80), shift=(80, 120, 80), pct=100)
    out = r.border_top(width=30, pill=pill)
    stripped = strip_ansi(out)
    assert _visible_width(out) == 30
    assert stripped[20] == PILL_TL
    assert stripped[29] == PILL_TR
    assert stripped[0] == '╭'


def test_border_separator_dim_right_flush_pill(r: borders.BorderRenderer) -> None:
    pill = Pill(start=21, end=30, anchor=(120, 80, 80), shift=(80, 120, 80), pct=100)
    out = r.border_separator_dim(width=30, ups=(5,), pill=pill)
    stripped = strip_ansi(out)
    assert _visible_width(out) == 30
    assert stripped[20] == PILL_BL
    assert stripped[29] == PILL_BR
    assert stripped[4] == '┴'
