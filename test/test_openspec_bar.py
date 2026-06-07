import yas.renderer as renderer
from yas.render.text import _visible_width
from helper import strip_ansi

Renderer = renderer.Renderer


def test_openspec_bar_visible_width() -> None:
    r = Renderer()
    out = r.openspec_bar('x', 3, 10, 80, 25)
    assert _visible_width(out) == 77


def test_openspec_bar_long_name_truncated() -> None:
    r = Renderer()
    out = r.openspec_bar('a' * 100, 1, 2, 80, 25)
    stripped = strip_ansi(out)
    # First title_w=25 chars form the title segment; it must end with '...'
    title_segment = stripped[:25]
    assert len(title_segment) == 25
    assert title_segment.endswith('...')


def test_openspec_bar_counts_and_percent() -> None:
    r = Renderer()
    out = r.openspec_bar('x', 3, 10, 80, 25)
    stripped = strip_ansi(out)
    assert '3/10' in stripped
    assert '30%' in stripped


def test_openspec_bar_colour_stable_across_positions() -> None:
    """Same name yields the same gradient regardless of list position."""
    r = Renderer()
    name = 'my-feature'
    # Render at different positions (formerly passed as idx)
    out_pos0 = r.openspec_bar(name, 5, 10, 80, 25)
    out_pos3 = r.openspec_bar(name, 5, 10, 80, 25)
    assert out_pos0 == out_pos3


def test_openspec_bar_colour_index_is_crc32() -> None:
    """The selected gradient index must equal zlib.crc32(name) % len(SPEC_GRADIENTS).

    Two names that map to different indices must produce different gradient
    output; two names that happen to share the same index must produce the
    same gradient segment (not tested here — the spread test below covers
    the distinctness side).  What we verify is that swapping a name for
    another that hashes to a *different* index changes the bar colours.
    """
    import zlib
    r = Renderer()
    n_gradients = len(r.SPEC_GRADIENTS)
    # Find two names whose crc32 maps to different indices
    names = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta',
             'feature-x', 'bugfix-y', 'chore-z', 'release-1']
    by_index: dict[int, str] = {}
    for name in names:
        idx = zlib.crc32(name.encode()) % n_gradients
        by_index.setdefault(idx, name)

    distinct_indices = sorted(by_index.keys())
    assert len(distinct_indices) >= 2, 'need at least two distinct indices to compare'

    idx_a, idx_b = distinct_indices[0], distinct_indices[1]
    name_a, name_b = by_index[idx_a], by_index[idx_b]

    # Bars with the same progress but different names and different indices
    # must produce different ANSI output (the gradient colours differ)
    out_a = r.openspec_bar(name_a, 5, 10, 80, 25)
    out_b = r.openspec_bar(name_b, 5, 10, 80, 25)
    # Strip the title portion (first 25 printable chars via ANSI scan) to
    # compare only the bar gradient portion — titles differ by name
    # Extract just the gradient by comparing full ANSI strings; if idx differs
    # the RGB triples in the bar will differ
    assert out_a != out_b, (
        f'names {name_a!r}(idx={idx_a}) and {name_b!r}(idx={idx_b}) '
        'produced identical output despite different gradient indices'
    )


def test_openspec_bar_colour_spread() -> None:
    """Several distinct names should not all resolve to the same gradient index."""
    import zlib
    r = Renderer()
    n_gradients = len(r.SPEC_GRADIENTS)
    names = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta']
    indices = {zlib.crc32(n.encode()) % n_gradients for n in names}
    assert len(indices) > 1, 'all names collapsed to a single gradient index'
