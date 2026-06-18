"""ASCII render mode (Config.ascii_mode / YAS_ASCII_MODE).

Proves the single final-pass str.translate seam in app.render:
  * a coverage guard so a future-added non-ASCII char in any constant can't
    silently bypass the fallback table (the most important invariant — now
    covers EVERY non-ASCII char, not just PUA),
  * every fallback is a single ASCII char (the width-preservation guarantee),
  * to_ascii leaves ANSI escapes and ordinary text untouched,
  * an end-to-end render contains ZERO codepoints >= 128 AND is per-line
    visible-width-identical to the normal render across all three layout
    builders (the column-math safety proof), and
  * Config resolution through every source (env / default / CLI / toml).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import yas.app as app
import yas.config as config
import yas.constants as c
from yas.constants import GLYPH_MODEL, GLYPH_THINKING
from yas.render.text import _visible_width, to_ascii

_EXAMPLE = Path(__file__).resolve().parent.parent / 'ops' / 'session-info-example.json'


def _load_example() -> dict:
    return json.loads(_EXAMPLE.read_text())


def _pua(ch: str) -> bool:
    return any(0xE000 <= ord(x) <= 0xF8FF or 0xF0000 <= ord(x) <= 0xFFFFD for x in ch)


def _non_ascii(ch: str) -> bool:
    return any(ord(x) >= 128 for x in ch)


def _string_constants() -> set[str]:
    """Every module-level str constant in yas.constants, plus the BarChars class
    attrs and the keys of ASCII_GLYPHS — the full universe of glyph literals the
    renderer can emit."""
    consts = {v for n, v in vars(c).items()
              if not n.startswith('_') and isinstance(v, str)}
    consts |= {v for v in vars(c.BarChars).values() if isinstance(v, str)}
    consts |= set(c.ASCII_GLYPHS)
    return consts


# --- 1. Coverage guard: every non-ASCII char in a constant has a fallback -----

def test_every_non_ascii_constant_char_has_ascii_fallback() -> None:
    missing: set[str] = set()
    for s in _string_constants():
        for ch in s:
            if ord(ch) >= 128 and ord(ch) not in c.ASCII_TRANSLATE:
                missing.add(ch)
    assert not missing, (
        f'non-ASCII constant chars lacking ascii fallback: '
        f'{sorted(hex(ord(ch)) for ch in missing)}')


# --- 2. Every fallback is a single ASCII char (width preservation) ------------

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


# --- 3. to_ascii correctness --------------------------------------------------

def test_to_ascii_replaces_pua_leaves_ansi_and_text() -> None:
    s = f'\033[31mhello {GLYPH_MODEL} world {GLYPH_THINKING}\033[0m'
    out = to_ascii(s)
    assert not _pua(out)
    assert c.ASCII_GLYPHS[GLYPH_MODEL] in out
    assert c.ASCII_GLYPHS[GLYPH_THINKING] in out
    # ANSI escapes and ordinary text untouched.
    assert '\033[31m' in out and '\033[0m' in out
    assert 'hello' in out and 'world' in out


def test_to_ascii_is_noop_on_plain_text() -> None:
    s = '\033[38;5;75m| path / branch |\033[0m'
    assert to_ascii(s) == s


# --- 4. End-to-end: pure-ASCII and width-identical per line -------------------

@pytest.mark.parametrize('width', [50, 70, 160])
def test_render_ascii_is_pure_ascii_and_width_identical(width: int) -> None:
    info = _load_example()
    normal = app.render(info, width)
    ascii_out = app.render(info, width, ascii_mode=True)

    # Headline invariant: not one codepoint >= 128 survives the ascii pass.
    offenders = sorted({hex(ord(ch)) for ch in ascii_out if ord(ch) >= 128})
    assert not offenders, f'ascii render at width={width} still has non-ASCII: {offenders}'

    n_lines = normal.split('\n')
    a_lines = ascii_out.split('\n')
    assert len(n_lines) == len(a_lines)
    for i, (nl, al) in enumerate(zip(n_lines, a_lines)):
        assert _visible_width(al) == _visible_width(nl), (
            f'line {i} width drift: ascii={_visible_width(al)} normal={_visible_width(nl)}')


# --- 5. Config resolution -----------------------------------------------------

def test_ascii_mode_env(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_ASCII_MODE': '1'}, config_dir=tmp_path)
    assert cfg.ascii_mode is True


def test_ascii_mode_default_false(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.ascii_mode is False


def test_ascii_mode_cli(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path, argv=['--ascii-mode'])
    assert cfg.ascii_mode is True


@pytest.mark.skipif(config.tomllib is None, reason='yas.toml parsing requires tomllib (Python 3.11+)')
def test_ascii_mode_toml(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[appearance]\nascii_mode = true\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.ascii_mode is True
