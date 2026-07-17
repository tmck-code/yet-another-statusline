"""Theme system tests.

The dataclass machinery catches typos and missing slots at import time — just
exercising every theme attribute is enough to assert structural completeness.
A byte-identity snapshot test for `claude-dark` × 3 layouts pins backward
compatibility against the canonical session-info fixture; light/Catppuccin
themes have no per-theme snapshots (curation choice, not regression target).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import yas.app as app
import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
from yas.config import Config
from yas.constants import BG_LUM_THRESHOLD, NARROW_WIDTH, MEDIUM_WIDTH
from yas.info import SessionView
from yas.themes import THEMES, CLAUDE_DARK, Theme
from yas.tokens import TickRecord, TokenLog

Theme    = Theme  # re-export for parametrize type hints

FIXTURES = Path(__file__).parent / 'fixtures'
SESSION  = (Path(__file__).parent.parent / 'ops'
            / 'session-info-example.json')


# Schema validation

EXPECTED_THEMES = {
    'claude-dark', 'claude-light',
    'catppuccin-mocha', 'catppuccin-latte',
    'dracula', 'gruvbox-dark', 'gruvbox-light', 'nord',
    'one-dark', 'one-light', 'palenight',
    'solarized-dark', 'solarized-light', 'tokyo-night',
}


def test_themes_registry_contains_expected() -> None:
    assert set(THEMES) == EXPECTED_THEMES


@pytest.mark.parametrize('theme_name', sorted(EXPECTED_THEMES))
def test_theme_has_every_slot_filled(theme_name: str) -> None:
    t = THEMES[theme_name]
    for name in Theme.__slots__:
        value = getattr(t, name)
        assert value is not None, f'{theme_name}: slot {name!r} is None'


@pytest.mark.parametrize('theme_name', sorted(EXPECTED_THEMES))
def test_theme_has_all_model_buckets(theme_name: str) -> None:
    t = THEMES[theme_name]
    assert set(t.models) == {'opus', 'sonnet', 'haiku', 'fable', 'mythos', 'other'}


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
        assert lum >= BG_LUM_THRESHOLD, (
            f'{theme_name}: {model} anchor lum={lum} '
            f'< threshold {BG_LUM_THRESHOLD}'
        )


# Theme resolution layering

def test_resolve_theme_defaults_to_claude_dark(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    monkeypatch.delenv('CLAUDE_STATUSLINE_THEME', raising=False)
    assert app.resolve_theme(None) is CLAUDE_DARK


def test_resolve_theme_cli_beats_env_and_file(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    monkeypatch.setenv('CLAUDE_STATUSLINE_THEME', 'dracula')
    (tmp_home / '.claude').mkdir(parents=True, exist_ok=True)
    (tmp_home / '.claude' / 'statusline-theme').write_text('claude-light\n')
    assert app.resolve_theme('nord') is THEMES['nord']


def test_resolve_theme_env_beats_file(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    monkeypatch.setenv('CLAUDE_STATUSLINE_THEME', 'dracula')
    (tmp_home / '.claude').mkdir(parents=True, exist_ok=True)
    (tmp_home / '.claude' / 'statusline-theme').write_text('claude-light\n')
    assert app.resolve_theme(None) is THEMES['dracula']


def test_resolve_theme_file_used_when_no_env(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    monkeypatch.delenv('CLAUDE_STATUSLINE_THEME', raising=False)
    (tmp_home / '.claude').mkdir(parents=True, exist_ok=True)
    (tmp_home / '.claude' / 'statusline-theme').write_text('claude-light')
    assert app.resolve_theme(None) is THEMES['claude-light']


def test_resolve_theme_unknown_name_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    monkeypatch.delenv('CLAUDE_STATUSLINE_THEME', raising=False)
    assert app.resolve_theme('no-such-theme') is CLAUDE_DARK


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
    import yas.renderer as _renderer_mod
    import time as _time_mod
    monkeypatch.setattr(_time_mod, 'time', lambda: float(FROZEN_EPOCH))
    monkeypatch.setattr(_renderer_mod.time, 'time', lambda: float(FROZEN_EPOCH))
    monkeypatch.setattr(_renderer_mod, 'datetime', _FrozenDatetime)
    yield


def _render(width: int, theme: Theme) -> str:
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    view    = SessionView(session, Config())
    r       = renderer_mod.Renderer(bg_shift='warm', theme=theme)
    if width < NARROW_WIDTH:
        spec = layout.build_narrow(view, width, r)
    elif width < MEDIUM_WIDTH:
        spec = layout.build_medium(view, width, r)
    else:
        tick = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
        spec = layout.build_wide(view, tick, width, r)
    return '\n'.join(layout.render_layout(spec, r))


@pytest.mark.parametrize('layout,width', [
    ('narrow', 50),
    ('medium', 74),
    ('wide',   120),
])
def test_claude_dark_byte_identity(layout: str, width: int, frozen, tmp_home) -> None:  # type: ignore[no-untyped-def]
    fixture = FIXTURES / f'claude_dark_{layout}.ansi'
    actual  = _render(width, CLAUDE_DARK)
    if not fixture.exists():
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text(actual)
        pytest.skip(f'wrote initial snapshot {fixture.name}')
    expected = fixture.read_text()
    assert actual == expected, (
        f'{layout} ({width}c) drifted from snapshot {fixture.name}. '
        f'If intentional, delete the fixture and re-run.'
    )
