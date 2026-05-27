"""The default glyphs must be universal — no Nerd-Font Private-Use codepoints
(which show as '?'/tofu without a Nerd Font). YAS_NERD_FONT=1 opts back in."""
import json
from pathlib import Path

import statusline_command as sl

_EXAMPLE = Path(__file__).resolve().parent.parent / 'claude' / 'statusline' / 'session-info-example.json'


def _is_pua(ch: str) -> bool:
    cp = ord(ch)
    return 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0xFFFFD


def test_no_glyph_constant_is_private_use_by_default() -> None:
    names = [n for n in dir(sl) if n.startswith(('GLYPH_', 'ICON_'))]
    assert names, 'expected GLYPH_/ICON_ constants'
    bad = {n: getattr(sl, n) for n in names
           if isinstance(getattr(sl, n), str) and any(_is_pua(c) for c in getattr(sl, n))}
    assert not bad, f'PUA glyphs present by default: {bad}'


def test_default_render_has_no_private_use_glyphs() -> None:
    info = json.loads(_EXAMPLE.read_text())
    for width in (50, 74, 140):
        out = sl.render(info, width)
        assert not any(_is_pua(c) for c in out), f'PUA char in render at width {width}'


def test_glyph_toggle_defaults_to_clean() -> None:
    assert sl._NERD_FONT is False            # YAS_NERD_FONT unset under tests
    assert sl._glyph('clean', 'nerd') == 'clean'
    assert sl.GLYPH_FOLDER == '●'       # disc, not the PUA folder glyph
