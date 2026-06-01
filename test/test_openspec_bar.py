import yas.renderer as renderer
from yas.render.text import _visible_width
from helper import strip_ansi

Renderer = renderer.Renderer


def test_openspec_bar_visible_width() -> None:
    r = Renderer()
    out = r.openspec_bar('x', 3, 10, 80, 25, 0)
    assert _visible_width(out) == 77


def test_openspec_bar_long_name_truncated() -> None:
    r = Renderer()
    out = r.openspec_bar('a' * 100, 1, 2, 80, 25, 0)
    stripped = strip_ansi(out)
    # First title_w=25 chars form the title segment; it must end with '...'
    title_segment = stripped[:25]
    assert len(title_segment) == 25
    assert title_segment.endswith('...')


def test_openspec_bar_counts_and_percent() -> None:
    r = Renderer()
    out = r.openspec_bar('x', 3, 10, 80, 25, 0)
    stripped = strip_ansi(out)
    assert '3/10' in stripped
    assert '30%' in stripped
