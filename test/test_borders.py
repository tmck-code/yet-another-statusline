import re

import pytest
import yas.render.borders as borders
import yas.render.gradient as gradient
import yas.renderer as renderer_mod
from yas.constants import PILL_LEFT, PILL_RIGHT, PILL_TL, PILL_TR, PILL_BL, PILL_BR
from yas.render.pill import Pill
from yas.render.text import _visible_width, superscript
from helper import strip_ansi

Renderer = renderer_mod.Renderer

_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _col_glyphs(line: str) -> list[tuple[str, str]]:
    """Split an ANSI border line into (ansi_prefix, glyph) per visible column.

    The accumulated ANSI escape runs since the previous glyph form that
    column's colour prefix; the next visible character is its glyph. This lets
    a test compare the colour and glyph at column N across two renders.
    """
    out: list[tuple[str, str]] = []
    prefix = ''
    i = 0
    while i < len(line):
        m = _ANSI.match(line, i)
        if m:
            prefix += m.group(0)
            i = m.end()
            continue
        out.append((prefix, line[i]))
        prefix = ''
        i += 1
    return out


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


def test_border_separator_downs_marker(r: borders.BorderRenderer) -> None:
    out = r.border_separator(width=20, downs=(7,))
    stripped = strip_ansi(out)
    assert _visible_width(out) == 20
    # downs=(7,): column 7 (1-based) → string index 6
    assert stripped[6] == '┬'


def test_border_separator_ups_marker(r: borders.BorderRenderer) -> None:
    out = r.border_separator(width=20, ups=(7,))
    stripped = strip_ansi(out)
    assert _visible_width(out) == 20
    assert stripped[6] == '┴'


def test_border_separator_down_and_up_coincide(r: borders.BorderRenderer) -> None:
    out = r.border_separator(width=20, ups=(7,), downs=(7,))
    stripped = strip_ansi(out)
    assert _visible_width(out) == 20
    # a column that is both a down and an up renders the cross elbow
    assert stripped[6] == '┼'


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


# --- label overlay (section 3) ------------------------------------------------

@pytest.mark.parametrize('method', ['border_top', 'border_separator', 'border_separator_dim'])
def test_label_width_preserved(r: borders.BorderRenderer, method: str) -> None:
    out = getattr(r, method)(width=60, labels=(('input', 20), ('cost', 40)))
    assert _visible_width(out) == 60


@pytest.mark.parametrize('method', ['border_top', 'border_separator', 'border_separator_dim'])
def test_label_differs_only_at_overlaid_columns(r: borders.BorderRenderer, method: str) -> None:
    # A labelled row equals its label-free counterpart everywhere except at the
    # label's own columns, guarding gradient coherence (each glyph keeps the
    # colour its fill char had — only the glyph itself changes).
    start = 20
    text = 'input'
    bare = getattr(r, method)(width=60)
    lab = getattr(r, method)(width=60, labels=((text, start),))
    bare_cols = _col_glyphs(bare)
    lab_cols = _col_glyphs(lab)
    assert len(bare_cols) == len(lab_cols)
    sup = superscript(text)
    label_idx = set(range(start - 1, start - 1 + len(sup)))
    for col, (b, l) in enumerate(zip(bare_cols, lab_cols)):
        if col in label_idx:
            # colour prefix unchanged; glyph swapped to the superscript form
            assert l[0] == b[0], col
            assert l[1] == sup[col - (start - 1)], col
        else:
            assert l == b, col


def test_label_truncates_before_elbow(r: borders.BorderRenderer) -> None:
    # 'session' (7 glyphs) anchored at col 20 with an elbow at col 24 → only
    # cols 20..23 are fill; the label truncates and the elbow survives.
    out = r.border_separator(width=60, downs=(24,), labels=(('session', 20),))
    stripped = strip_ansi(out)
    assert stripped[23] == '┬'  # elbow (col 24) intact
    sup = superscript('session')
    assert stripped[19:23] == sup[:4]  # first 4 glyphs written
    # the 5th glyph would have landed on the elbow column — it must not appear
    assert sup[4] != '┬'
    assert _visible_width(out) == 60


def test_label_dropped_when_anchor_is_elbow(r: borders.BorderRenderer) -> None:
    # Anchor sits on an elbow column → label dropped entirely, output unchanged.
    bare = r.border_separator(width=60, downs=(20,))
    lab = r.border_separator(width=60, downs=(20,), labels=(('input', 20),))
    assert bare == lab


def test_label_dropped_on_session_id(r: borders.BorderRenderer) -> None:
    # Anchor inside the embedded session-id region of the top border → dropped,
    # session id rendered intact.
    sid = 'abc-123-session'
    bare = r.border_top(width=60, session_id=sid)
    lab = r.border_top(width=60, session_id=sid, labels=(('input', 5),))
    assert bare == lab
    assert sid in strip_ansi(lab)


def test_label_carries_per_column_gradient_colour(r: borders.BorderRenderer) -> None:
    # Each label glyph's ANSI prefix equals the fill char's prefix at that column.
    bare = _col_glyphs(r.border_top(width=80))
    lab = _col_glyphs(r.border_top(width=80, labels=(('tokens', 30),)))
    for col in range(29, 29 + len('tokens')):
        assert lab[col][0] == bare[col][0], col


def test_dim_label_inherits_dim_factor(r: borders.BorderRenderer) -> None:
    # On the dim separator the per-column dim factor is baked into the colour
    # prefix, so a label glyph at column N carries the same prefix the dotted
    # fill had there. Place the label away from the elbow so the dim ramp is in
    # effect.
    bare = _col_glyphs(r.border_separator_dim(width=80, ups=(10,)))
    lab = _col_glyphs(r.border_separator_dim(width=80, ups=(10,), labels=(('cache', 40),)))
    for col in range(39, 39 + len('cache')):
        assert lab[col][0] == bare[col][0], col


def test_pill_columns_protected_from_label_top(r: borders.BorderRenderer) -> None:
    # A label whose run would cross the pill must stop at the pill edge; pill
    # columns are never overwritten.
    pill = Pill(start=21, end=30, anchor=(120, 80, 80), shift=(80, 120, 80), pct=100)
    bare = r.border_top(width=40, pill=pill)
    lab = r.border_top(width=40, pill=pill, labels=(('skills + plugins', 18),))
    bare_s = strip_ansi(bare)
    lab_s = strip_ansi(lab)
    # pill columns 21..30 (idx 20..29) unchanged
    assert bare_s[20:30] == lab_s[20:30]
    assert bare_s[20] == PILL_TL
    assert _visible_width(lab) == 40


def test_pill_columns_protected_from_label_dim(r: borders.BorderRenderer) -> None:
    pill = Pill(start=21, end=30, anchor=(120, 80, 80), shift=(80, 120, 80), pct=100)
    bare = r.border_separator_dim(width=40, ups=(5,), pill=pill)
    lab = r.border_separator_dim(width=40, ups=(5,), pill=pill, labels=(('input', 18),))
    bare_s = strip_ansi(bare)
    lab_s = strip_ansi(lab)
    assert bare_s[20:30] == lab_s[20:30]
    assert bare_s[20] == PILL_BL
    assert _visible_width(lab) == 40
