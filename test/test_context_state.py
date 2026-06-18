"""Tests for the context-state word (ported from Dumbometer, MIT).

Covers three layers: the pure label mapping (``yas.context_state``), the config
knobs (``[context]`` table / ``YAS_CONTEXT_*`` env), and the renderer wiring in
``Renderer.context_line``.
"""

import re

import pytest

import yas.config as config
import yas.renderer as renderer
from yas.constants import (
    DEFAULT_CONTEXT_LABELS,
    DEFAULT_CONTEXT_THRESHOLDS,
)
from yas.context_state import context_state
from yas.render.text import _visible_width
from yas.session import ContextWindow

Renderer = renderer.Renderer

_ANSI = re.compile(r'\x1b\[[^m]*m')


def _strip(s: str) -> str:
    return _ANSI.sub('', s)


# ---------------------------------------------------------------------------
# Pure mapping
# ---------------------------------------------------------------------------

L = DEFAULT_CONTEXT_LABELS
T = DEFAULT_CONTEXT_THRESHOLDS


@pytest.mark.parametrize(
    'pct,expected',
    [
        (0, 'Smart'), (24, 'Smart'),
        (25, 'Coasting'), (49, 'Coasting'),
        (50, 'Foggy'), (69, 'Foggy'),
        (70, 'Cooked'), (89, 'Cooked'),
        (90, 'Dumb'), (100, 'Dumb'),
    ],
)
def test_default_band_boundaries(pct: int, expected: str) -> None:
    # Lower edge is inclusive (>=), matching Dumbometer's computeState.
    assert context_state(pct, L, T) == expected


def test_out_of_range_is_clamped() -> None:
    assert context_state(-10, L, T) == 'Smart'
    assert context_state(150, L, T) == 'Dumb'


def test_empty_labels_returns_empty() -> None:
    assert context_state(50, (), T) == ''


def test_custom_labels_and_thresholds() -> None:
    labels = ('A', 'B', 'C', 'D', 'E')
    thresholds = (10, 20, 30, 40)
    assert context_state(5, labels, thresholds) == 'A'
    assert context_state(10, labels, thresholds) == 'B'
    assert context_state(35, labels, thresholds) == 'D'
    assert context_state(99, labels, thresholds) == 'E'


def test_index_never_exceeds_labels() -> None:
    # More thresholds than labels-1 must clamp to the last label, not raise.
    assert context_state(100, ('only', 'two'), (10, 20, 30, 40)) == 'two'


# ---------------------------------------------------------------------------
# Config knobs
# ---------------------------------------------------------------------------

def test_defaults_off_and_canonical_labels() -> None:
    cfg = config.Config.load(env={})
    assert cfg.context_state is False
    assert cfg.context_labels == DEFAULT_CONTEXT_LABELS
    assert cfg.context_thresholds == DEFAULT_CONTEXT_THRESHOLDS


def test_env_enables_and_overrides() -> None:
    cfg = config.Config.load(env={
        'YAS_CONTEXT_STATE': '1',
        'YAS_CONTEXT_LABELS': 'A,B,C,D,E',
        'YAS_CONTEXT_THRESHOLDS': '10,20,30,40',
    })
    assert cfg.context_state is True
    assert cfg.context_labels == ('A', 'B', 'C', 'D', 'E')
    assert cfg.context_thresholds == (10, 20, 30, 40)


def test_empty_env_falls_back() -> None:
    cfg = config.Config.load(env={'YAS_CONTEXT_STATE': '', 'YAS_CONTEXT_LABELS': ''})
    assert cfg.context_state is False
    assert cfg.context_labels == DEFAULT_CONTEXT_LABELS


def test_bad_labels_fall_back_silently_from_env() -> None:
    # Wrong count → default; env rejections are debug-only (not in the error row).
    cfg = config.Config.load(env={'YAS_CONTEXT_LABELS': 'only,three,here'})
    assert cfg.context_labels == DEFAULT_CONTEXT_LABELS
    assert 'context_labels' not in cfg.errors


@pytest.mark.parametrize('bad', ['1,2,3', '1,2,3,4,5', '40,30,20,10', '0,1,2,3', '10,20,30,100'])
def test_bad_thresholds_fall_back(bad: str) -> None:
    cfg = config.Config.load(env={'YAS_CONTEXT_THRESHOLDS': bad})
    assert cfg.context_thresholds == DEFAULT_CONTEXT_THRESHOLDS


def test_toml_rejection_surfaces_in_error_row(tmp_path) -> None:
    (tmp_path / 'yas.toml').write_text('[context]\nlabels = ["too", "few"]\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.context_labels == DEFAULT_CONTEXT_LABELS
    assert 'context_labels' in cfg.errors


def test_toml_valid_context_table(tmp_path) -> None:
    (tmp_path / 'yas.toml').write_text(
        '[context]\nstate = true\nthresholds = [20, 40, 60, 80]\n'
    )
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.context_state is True
    assert cfg.context_thresholds == (20, 40, 60, 80)


def test_env_beats_toml(tmp_path) -> None:
    (tmp_path / 'yas.toml').write_text('[context]\nstate = false\n')
    cfg = config.Config.load(env={'YAS_CONTEXT_STATE': '1'}, config_dir=tmp_path)
    assert cfg.context_state is True


# ---------------------------------------------------------------------------
# Renderer wiring
# ---------------------------------------------------------------------------

def _ctx(used: int, window: int = 200_000) -> ContextWindow:
    return ContextWindow(total_input_tokens=used, total_output_tokens=0, context_window_size=window)


def test_word_absent_by_default() -> None:
    # No state args → byte output unchanged (opt-in feature).
    r = Renderer()
    out = _strip(r.context_line(_ctx(30_000), available=76))
    assert not any(lbl in out for lbl in DEFAULT_CONTEXT_LABELS)


def test_word_present_when_enabled() -> None:
    r = Renderer()
    out = _strip(r.context_line(_ctx(30_000), available=76, state_labels=L, state_thresholds=T))
    # 30k / 150k soft limit = 20% → Smart.
    assert 'Smart' in out


def test_word_tracks_fill() -> None:
    r = Renderer()
    # 120k / 150k = 80% → Cooked.
    out = _strip(r.context_line(_ctx(120_000), available=76, state_labels=L, state_thresholds=T))
    assert 'Cooked' in out


def test_word_padded_to_widest_label() -> None:
    r = Renderer()
    out = _strip(r.context_line(_ctx(30_000), available=76, state_labels=L, state_thresholds=T))
    # 'Smart' padded to width of 'Coasting' (8) → followed by spaces before the bar.
    assert 'Smart   ' in out


def test_word_respects_width_budget() -> None:
    r = Renderer()
    out = r.context_line(_ctx(30_000), available=76, state_labels=L, state_thresholds=T)
    assert _visible_width(out) <= 76


def test_word_sheds_when_too_narrow() -> None:
    # A tight available width must drop the word so the bar stays legible.
    r = Renderer()
    out = _strip(r.context_line(_ctx(30_000), available=28, state_labels=L, state_thresholds=T))
    assert 'Smart' not in out


def test_word_renders_over_soft_limit() -> None:
    r = Renderer()
    out = _strip(r.context_line(_ctx(300_000), available=76, state_labels=L, state_thresholds=T))
    assert 'Dumb' in out
