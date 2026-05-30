'''Tests for the width/overflow cluster (Audit CWIDTH / CTRUNC / MODELW):
wide-character width accounting, middle-ellipsis budget safety, and bounded model
name in the wide layout.'''
import re

import statusline_command as sl
from statusline.textutil import _char_width, _is_wide, _middle_ellipsis, _visible_width


def _plain(s: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', s)


# ---------------------------------------------------------------- CWIDTH
def test_char_width_wide_and_zero():
    assert _char_width('A') == 1
    assert _char_width('漢') == 2       # CJK ideograph (EAW=W)
    assert _char_width('한') == 2       # Hangul syllable (EAW=W)
    assert _char_width('Ａ') == 2       # fullwidth Latin (EAW=F)
    assert _char_width('́') == 0   # combining acute accent
    assert _char_width('‍') == 0   # zero-width joiner (Cf)
    assert _char_width('😀') == 2       # emoji pictograph


def test_visible_width_counts_wide():
    assert _visible_width('漢字') == 4
    assert _visible_width('한글') == 4
    assert _visible_width('abc') == 3
    assert _visible_width('é') == 1   # base + combining = 1 cell


def test_visible_width_no_regression_on_render_glyphs():
    # Box-drawing, block, and ellipsis glyphs must stay 1 cell (EAW=A/N) so
    # existing layouts/snapshots don't shift.
    for ch in '╭╮╰╯│├┤─░▌█●…':
        assert _char_width(ch) == 1, ch


def test_is_wide_matches_char_width():
    assert _is_wide('漢') is True
    assert _is_wide('a') is False


# ---------------------------------------------------------------- CTRUNC
def test_middle_ellipsis_never_exceeds_budget_wide():
    # The pre-fix code overshot the budget by up to 26 cells on wide/emoji input.
    over = 0
    for n in range(2, 40):
        for mw in range(2, 30):
            for ch in ('漢', '😀'):
                r = _middle_ellipsis(ch * n, mw)
                if _visible_width(r) > mw:
                    over += 1
    assert over == 0


def test_middle_ellipsis_ascii_unchanged():
    assert _middle_ellipsis('abcdefghij', 100) == 'abcdefghij'   # fits -> verbatim
    out = _middle_ellipsis('abcdefghij', 7)
    assert '…' in out and _visible_width(out) <= 7


# ---------------------------------------------------------------- MODELW
def _render(model_name: str, width: int) -> str:
    return sl.render({
        'session_id': 's', 'model': {'display_name': model_name},
        'workspace': {'current_dir': '/tmp/p'},
        'context_window': {'total_input_tokens': 40000, 'context_window_size': 200000},
    }, width, theme=sl.CLAUDE_DARK)


def test_long_model_name_does_not_overflow_box():
    longname = 'Opus-Maximum-Reasoning-Engine-9000-with-extended-context' * 3
    for w in (90, 110, 130, 140):
        out = _render(longname, w)
        for line in _plain(out).splitlines():
            assert _visible_width(line) <= w, f'overflow at width {w}'


def test_normal_model_name_unchanged():
    out = _plain(_render('Opus 4.1', 130))
    assert 'Opus 4.1' in out
