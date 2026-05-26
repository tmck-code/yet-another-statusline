"""Theme system tests.

The dataclass machinery catches typos and missing slots at import time — just
exercising every theme attribute is enough to assert structural completeness.
A byte-identity snapshot test for `claude-dark` × 3 layouts pins backward
compatibility against the canonical session-info fixture; light/Catppuccin
themes have no per-theme snapshots (curation choice, not regression target).
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

import statusline_command as sl

THEMES   = sl.THEMES
Theme    = sl.Theme

FIXTURES = Path(__file__).parent / 'fixtures'
SESSION  = (Path(__file__).parent.parent / 'claude' / 'statusline'
            / 'session-info-example.json')


# Schema validation

EXPECTED_THEMES = {
    'claude-dark', 'claude-light', 'catppuccin-latte', 'catppuccin-mocha',
}


def test_themes_registry_contains_expected() -> None:
    assert set(THEMES) == EXPECTED_THEMES


@pytest.mark.parametrize('theme_name', sorted(EXPECTED_THEMES))
def test_theme_has_every_slot_filled(theme_name: str) -> None:
    t = THEMES[theme_name]
    for f in fields(Theme):
        value = getattr(t, f.name)
        assert value is not None, f'{theme_name}: slot {f.name!r} is None'


@pytest.mark.parametrize('theme_name', sorted(EXPECTED_THEMES))
def test_theme_has_all_four_models(theme_name: str) -> None:
    t = THEMES[theme_name]
    assert set(t.models) == {'opus', 'sonnet', 'haiku', 'other'}


@pytest.mark.parametrize('theme_name', sorted(EXPECTED_THEMES))
def test_theme_anchor_luminance_triggers_flip(theme_name: str) -> None:
    """Every model anchor's luminance must be ≥ BG_LUM_THRESHOLD so the
    two-sided pill foreground flip resolves to `pill_fg_dark` on bright bg.
    Anchors below threshold would render text the same colour as the dim
    background → invisible. See ADR-0002."""
    t = THEMES[theme_name]
    for model, mc in t.models.items():
        r, g, b = mc.anchor
        lum = (r * 299 + g * 587 + b * 114) // 1000
        assert lum >= sl.BG_LUM_THRESHOLD, (
            f'{theme_name}: {model} anchor lum={lum} '
            f'< threshold {sl.BG_LUM_THRESHOLD}'
        )


# Theme resolution layering

def test_resolve_theme_defaults_to_claude_dark(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    monkeypatch.delenv('CLAUDE_STATUSLINE_THEME', raising=False)
    assert sl.resolve_theme(None) is sl.CLAUDE_DARK


def test_resolve_theme_cli_beats_env_and_file(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    monkeypatch.setenv('CLAUDE_STATUSLINE_THEME', 'catppuccin-mocha')
    (tmp_home / '.claude').mkdir(parents=True, exist_ok=True)
    (tmp_home / '.claude' / 'statusline-theme').write_text('claude-light\n')
    assert sl.resolve_theme('catppuccin-latte') is THEMES['catppuccin-latte']


def test_resolve_theme_env_beats_file(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    monkeypatch.setenv('CLAUDE_STATUSLINE_THEME', 'catppuccin-mocha')
    (tmp_home / '.claude').mkdir(parents=True, exist_ok=True)
    (tmp_home / '.claude' / 'statusline-theme').write_text('claude-light\n')
    assert sl.resolve_theme(None) is THEMES['catppuccin-mocha']


def test_resolve_theme_file_used_when_no_env(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    monkeypatch.delenv('CLAUDE_STATUSLINE_THEME', raising=False)
    (tmp_home / '.claude').mkdir(parents=True, exist_ok=True)
    (tmp_home / '.claude' / 'statusline-theme').write_text('claude-light')
    assert sl.resolve_theme(None) is THEMES['claude-light']


def test_resolve_theme_unknown_name_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    monkeypatch.delenv('CLAUDE_STATUSLINE_THEME', raising=False)
    assert sl.resolve_theme('no-such-theme') is sl.CLAUDE_DARK


# Byte-identity snapshot — claude-dark × 3 layouts
#
# The rendered statusline encodes (a) the rate-limit countdown derived from
# `datetime.now()` vs the fixture's `resets_at`, (b) the rainbow phase
# derived from `time.time()`, and (c) the day-token/cost totals the wide
# layout reads from `CLAUDE_DIR/statusline-tokens.log`. (a) and (b) are
# frozen by the `frozen` fixture; (c) is isolated by the `tmp_home` fixture,
# which points CLAUDE_DIR at an empty tmp dir so day totals resolve to 0
# (and the developer's real token log is never read or written). Without it
# the wide snapshot drifts on any machine with usage logged on FROZEN's date.

FROZEN_EPOCH = 1776800000  # arbitrary fixed point before the fixture's resets_at
FROZEN_DT    = None        # initialised lazily inside _freeze


class _FrozenDatetime:
    """Stub replacing `datetime.datetime` on the sl module — only the bits
    `model_*_section` actually call are stubbed."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[no-untyped-def]
        from datetime import datetime, timezone
        return datetime.fromtimestamp(FROZEN_EPOCH, tz=tz or timezone.utc)

    @classmethod
    def fromtimestamp(cls, ts, tz=None):  # type: ignore[no-untyped-def]
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=tz or timezone.utc)


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sl.time, 'time', lambda: float(FROZEN_EPOCH))
    monkeypatch.setattr(sl, 'datetime', _FrozenDatetime)
    yield


def _render(width: int, theme: Theme) -> str:
    session = sl.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    r       = sl.Renderer(bg_shift='warm', theme=theme)
    if width < sl.NARROW_WIDTH:
        spec = sl.build_narrow(session, width, r)
    elif width < sl.MEDIUM_WIDTH:
        spec = sl.build_medium(session, width, r)
    else:
        spec = sl.build_wide(session, width, r)
    return '\n'.join(sl.render_layout(spec, r))


@pytest.mark.parametrize('layout,width', [
    ('narrow', 50),
    ('medium', 74),
    ('wide',   120),
])
def test_claude_dark_byte_identity(layout: str, width: int, frozen, tmp_home) -> None:  # type: ignore[no-untyped-def]
    fixture = FIXTURES / f'claude_dark_{layout}.ansi'
    actual  = _render(width, sl.CLAUDE_DARK)
    if not fixture.exists():
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text(actual)
        pytest.skip(f'wrote initial snapshot {fixture.name}')
    expected = fixture.read_text()
    assert actual == expected, (
        f'{layout} ({width}c) drifted from snapshot {fixture.name}. '
        f'If intentional, delete the fixture and re-run.'
    )
