"""Glyph-mode render suite (Config.glyph_mode / YAS_GLYPH_MODE).

Proves the single final-pass seam in app.render that applies one of four
mutually-exclusive glyph modes (nerdfont|ascii|unicode|singlewidth):
  * coverage guards so a future-added non-ASCII char in any constant can't
    silently bypass the ascii table, and every PUA icon has a unicode fallback,
  * every fallback is a single width-1 char (the width-preservation guarantee),
  * to_ascii leaves ANSI escapes and ordinary text untouched,
  * an end-to-end render is per-line visible-width-identical to the nerdfont
    render across all three layout builders for every mode that does not fold
    wide content (the column-math safety proof), and the per-mode content
    invariants: ascii has zero codepoints >= 128; unicode has zero PUA but keeps
    box/block/arrow glyphs; singlewidth folds injected wide dynamic content;
    nerdfont is identity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import yas.app as app
import yas.constants as c
from yas.constants import GLYPH_MODEL, GLYPH_THINKING
from yas.render.text import _is_wide, _visible_width, apply_glyph_mode, to_ascii, to_singlewidth

_EXAMPLE = Path(__file__).resolve().parent.parent / 'ops' / 'session-info-example.json'

MODES = ['nerdfont', 'ascii', 'unicode', 'singlewidth']


def _load_example() -> dict:
    return json.loads(_EXAMPLE.read_text())


def _pua(ch: str) -> bool:
    return any(0xE000 <= ord(x) <= 0xF8FF or 0xF0000 <= ord(x) <= 0xFFFFD for x in ch)


def _string_constants() -> set[str]:
    """Every module-level str constant in yas.constants, plus the BarChars class
    attrs and the keys of ASCII_GLYPHS — the full universe of glyph literals the
    renderer can emit."""
    consts = {v for n, v in vars(c).items()
              if not n.startswith('_') and isinstance(v, str)}
    consts |= {v for v in vars(c.BarChars).values() if isinstance(v, str)}
    consts |= set(c.ASCII_GLYPHS)
    return consts


# --- 1. Coverage guards -------------------------------------------------------

def test_every_non_ascii_constant_char_has_ascii_fallback() -> None:
    missing: set[str] = set()
    for s in _string_constants():
        for ch in s:
            if ord(ch) >= 128 and ord(ch) not in c.ASCII_TRANSLATE:
                missing.add(ch)
    assert not missing, (
        f'non-ASCII constant chars lacking ascii fallback: '
        f'{sorted(hex(ord(ch)) for ch in missing)}')


def test_every_pua_glyph_has_ascii_and_unicode_fallback() -> None:
    """Every PUA icon the statusline emits must have an entry in BOTH tables, and
    every UNICODE_PUA value must be a single non-PUA char (the drift guard from
    design.md decision 4 — two divergent tables, caught at build time)."""
    pua_glyphs = {g for g in c.ASCII_GLYPHS if _pua(g)}
    for g in pua_glyphs:
        assert g in c.UNICODE_PUA, f'PUA glyph {hex(ord(g))} missing from UNICODE_PUA'
    for g, u in c.UNICODE_PUA.items():
        assert _pua(g), f'UNICODE_PUA key {hex(ord(g))} is not PUA'
        assert g in c.ASCII_GLYPHS, f'UNICODE_PUA key {hex(ord(g))} missing from ASCII_GLYPHS'
        assert len(u) == 1, f'UNICODE_PUA value for {hex(ord(g))} not length 1: {u!r}'
        assert not _pua(u), f'UNICODE_PUA value {u!r} is itself PUA'


def test_all_fallbacks_are_single_ascii_chars() -> None:
    for glyph, fallback in c.ASCII_GLYPHS.items():
        assert len(fallback) == 1, f'fallback for {hex(ord(glyph))} is not length 1: {fallback!r}'
        assert ord(fallback) < 128, f'fallback for {hex(ord(glyph))} is non-ascii: {fallback!r}'


def test_ramp_fallbacks_are_single_ascii_chars() -> None:
    for cp, fallback in c._RAMP_FALLBACK.items():
        assert len(fallback) == 1, f'ramp fallback for {hex(cp)} is not length 1: {fallback!r}'
        assert ord(fallback) < 128, f'ramp fallback for {hex(cp)} is non-ascii: {fallback!r}'


def test_translate_table_values_are_single_ascii_chars() -> None:
    for cp, fallback in c.ASCII_TRANSLATE.items():
        assert len(fallback) == 1 and ord(fallback) < 128, (
            f'translate entry {hex(cp)} -> {fallback!r} is not single-ascii')


# --- 2. to_ascii / apply_glyph_mode unit correctness --------------------------

def test_to_ascii_replaces_pua_leaves_ansi_and_text() -> None:
    s = f'\033[31mhello {GLYPH_MODEL} world {GLYPH_THINKING}\033[0m'
    out = to_ascii(s)
    assert not _pua(out)
    assert c.ASCII_GLYPHS[GLYPH_MODEL] in out
    assert c.ASCII_GLYPHS[GLYPH_THINKING] in out
    assert '\033[31m' in out and '\033[0m' in out
    assert 'hello' in out and 'world' in out


def test_to_ascii_is_noop_on_plain_text() -> None:
    s = '\033[38;5;75m| path / branch |\033[0m'
    assert to_ascii(s) == s


def test_apply_glyph_mode_nerdfont_is_identity() -> None:
    s = f'\033[31m{GLYPH_MODEL} {c.BarChars.MID} text {GLYPH_THINKING}\033[0m'
    assert apply_glyph_mode(s, 'nerdfont') == s


def test_apply_glyph_mode_unicode_removes_pua() -> None:
    s = f'{GLYPH_MODEL} {GLYPH_THINKING} {c.BarChars.MID}'
    out = apply_glyph_mode(s, 'unicode')
    assert not _pua(out)
    assert c.UNICODE_PUA[GLYPH_MODEL] in out


def test_to_singlewidth_folds_wide_keeps_narrow() -> None:
    s = 'x\U0001F525yz'  # narrow + fire emoji (wide) + narrow + a PUA icon (width-1)
    out = to_singlewidth(s)
    assert not any(_is_wide(ch) for ch in out)
    assert _visible_width(out) == _visible_width(s) - 1  # the one wide char folds 2 -> 1
    assert '' in out  # width-1 PUA glyph left untouched


# --- 3. End-to-end: width-identical per line across non-folding modes ----------

@pytest.mark.parametrize('width', [50, 70, 160])
@pytest.mark.parametrize('mode', MODES)
def test_render_width_identical_to_nerdfont(mode: str, width: int) -> None:
    info = _load_example()  # clean example has no genuinely-wide chars
    base = app.render(info, width, glyph_mode='nerdfont')
    out = app.render(info, width, glyph_mode=mode)
    b_lines, o_lines = base.split('\n'), out.split('\n')
    assert len(b_lines) == len(o_lines)
    for i, (bl, ol) in enumerate(zip(b_lines, o_lines)):
        assert _visible_width(ol) == _visible_width(bl), (
            f'mode={mode} width={width} line {i} drift: '
            f'{_visible_width(ol)} != nerdfont {_visible_width(bl)}')


# --- 4. Per-mode content invariants -------------------------------------------

@pytest.mark.parametrize('width', [50, 70, 160])
def test_nerdfont_is_byte_identical_to_default(width: int) -> None:
    info = _load_example()
    assert app.render(info, width, glyph_mode='nerdfont') == app.render(info, width)


@pytest.mark.parametrize('width', [50, 70, 160])
def test_ascii_mode_is_pure_ascii(width: int) -> None:
    info = _load_example()
    out = app.render(info, width, glyph_mode='ascii')
    offenders = sorted({hex(ord(ch)) for ch in out if ord(ch) >= 128})
    assert not offenders, f'ascii render at width={width} still has non-ASCII: {offenders}'


@pytest.mark.parametrize('width', [50, 70, 160])
def test_unicode_mode_has_no_pua_but_keeps_box(width: int) -> None:
    info = _load_example()
    out = app.render(info, width, glyph_mode='unicode')
    offenders = sorted({hex(ord(ch)) for ch in out if _pua(ch)})
    assert not offenders, f'unicode render at width={width} still has PUA: {offenders}'
    # box-drawing / block / arrow glyphs are standard Unicode and stay intact.
    assert c.BOX_H in out or c.BOX_V in out, 'box-drawing glyphs should survive unicode mode'


def test_singlewidth_folds_injected_wide_dynamic_content() -> None:
    info = _load_example()
    info['model']['display_name'] = 'Son\U0001F525net'  # survives the render verbatim
    nerd = app.render(info, 160, glyph_mode='nerdfont')
    assert any(_is_wide(ch) for ch in nerd), 'fixture should render a wide char in nerdfont mode'
    sw = app.render(info, 160, glyph_mode='singlewidth')
    assert not any(_is_wide(ch) for ch in sw), 'singlewidth must fold every wide char'
    assert sw == to_singlewidth(nerd)  # the mode is exactly the full-render fold
