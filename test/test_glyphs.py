"""The default glyphs must be universal — renderable in any ordinary monospace
font. That rules out not just Nerd-Font Private-Use codepoints, but also the
"heavy arrows" (U+1F8xx) and "Symbols for Legacy Computing" (U+1FBxx) blocks,
which almost no font ships (they show as '?'/tofu). YAS_NERD_FONT=1 opts back in.

Regression note: an earlier version only scanned the *example* render, which has
inactive tokens and no rate history, so it never exercised the in/out token
arrows or the rate sparkline — the two places real sessions still showed '?'.
"""
import json
from pathlib import Path

import pytest

import statusline_command as sl

_EXAMPLE = Path(__file__).resolve().parent.parent / 'claude' / 'statusline' / 'session-info-example.json'


def _bad(ch: str) -> bool:
    """True for codepoints that ordinary monospace fonts don't render."""
    cp = ord(ch)
    return (
        0xE000  <= cp <= 0xF8FF  or 0xF0000 <= cp <= 0xFFFFD   # Private Use Areas (Nerd glyphs)
        or 0x1F800 <= cp <= 0x1F8FF                            # Supplemental Arrows-C (🡅/🡇)
        or 0x1FB00 <= cp <= 0x1FBFF                            # Symbols for Legacy Computing (sparkline diagonals)
        or 0x1F300 <= cp <= 0x1FAFF                            # emoji / pictographs
    )


def _offenders(s: str) -> list[str]:
    return sorted({hex(ord(c)) for c in s if _bad(c)})


def test_no_glyph_constant_is_private_use_by_default() -> None:
    names = [n for n in dir(sl) if n.startswith(('GLYPH_', 'ICON_'))]
    assert names, 'expected GLYPH_/ICON_ constants'
    bad = {n: getattr(sl, n) for n in names
           if isinstance(getattr(sl, n), str) and _offenders(getattr(sl, n))}
    assert not bad, f'unsupported glyphs present by default: {bad}'


def test_default_render_uses_only_widely_supported_glyphs() -> None:
    info = json.loads(_EXAMPLE.read_text())
    for width in (50, 74, 140):
        out = sl.render(info, width)
        assert not _offenders(out), f'unsupported glyph(s) at width {width}: {_offenders(out)}'


def test_sparkline_emits_only_universal_glyphs() -> None:
    # Exercises both rows (idx 9+ carries into the top row) — the old diagonal
    # "rise/fall" glyphs lived here and rendered as '?'.
    top, bot = sl.Renderer().sparkline([0, 1, 4, 8, 16, 10, 3, 12, 7, 0])
    assert not _offenders(top + bot), f'sparkline emitted: {_offenders(top + bot)}'


def test_token_arrows_universal_even_when_active(monkeypatch: pytest.MonkeyPatch) -> None:
    # The in/out arrows use Nerd "heavy arrows" only behind YAS_NERD_FONT; the
    # clean default must stay universal even when tokens are actively flowing
    # (the inactive branch the example happens to hit is not enough coverage).
    monkeypatch.setattr(sl.TokenRate, 'recently_active', lambda *a, **k: (True, True))
    rows, _, _ = sl.Renderer().tokens_cost(
        1_600_000, 120_000, 749_300, 80_100_000, 5_000_000, 3_200_000,
        73.71, 210.50, 10_900, session_id='', box_width=120,
    )
    blob = ''.join(rows)
    assert not _offenders(blob), f'token row emitted: {_offenders(blob)}'


def test_glyph_toggle_defaults_to_clean() -> None:
    assert sl._NERD_FONT is False            # YAS_NERD_FONT unset under tests
    assert sl._glyph('clean', 'nerd') == 'clean'
    assert sl.GLYPH_FOLDER == '●'       # disc, not the PUA folder glyph
