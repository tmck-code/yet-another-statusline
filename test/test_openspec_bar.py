import statusline_command as sl
from conftest import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer


def test_openspec_bar_visible_width():
    r = Renderer()
    out = r.openspec_bar('x', 3, 10, 80, 25, 0)
    assert _visible_width(out) == 77


def test_openspec_bar_long_name_truncated():
    r = Renderer()
    out = r.openspec_bar('a' * 100, 1, 2, 80, 25, 0)
    stripped = strip_ansi(out)
    # First title_w=25 chars form the title segment; it must end with '...'
    title_segment = stripped[:25]
    assert len(title_segment) == 25
    assert title_segment.endswith('...')


def test_openspec_bar_counts_and_percent():
    r = Renderer()
    out = r.openspec_bar('x', 3, 10, 80, 25, 0)
    stripped = strip_ansi(out)
    assert '3/10' in stripped
    assert '30%' in stripped
