"""Config resolution tests (OpenSpec Group 4).

Exercises `Config.load` precedence (CLI → canonical env → legacy alias → yas.toml
→ default), per-knob validation/fallback, error recording, the Python-3.10
tomllib-missing degrade path, per-model `soft_limit_for`, and the visible
config-error row (`append_error_row` plus an end-to-end `render` box-integrity
check). All toml is written into pytest's `tmp_path` and passed via
`config_dir=`; `env` is always an explicit dict so the real environment never
leaks in.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import yas.app as app
import yas.config as config
import yas.renderer as renderer_mod
from yas.constants import GLYPH_CONFIG_WARN
from yas.layout import RowSpec, append_error_row
from yas.render.text import _visible_width
from yas.themes import CLAUDE_DARK

SESSION = (Path(__file__).parent.parent / 'ops'
           / 'session-info-example.json')

# yas.toml parsing needs stdlib tomllib (Python 3.11+). On 3.10 the file is
# silently skipped (env + defaults still apply — see the degrade test below),
# so tests that assert toml-sourced values are applied can't run there.
requires_tomllib = pytest.mark.skipif(
    config.tomllib is None, reason='yas.toml parsing requires tomllib (Python 3.11+)',
)


# 4.1 Precedence chain: env > toml > default

def test_env_overrides_toml(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nmax_width = 200\n')
    cfg = config.Config.load(env={'YAS_MAX_WIDTH': '160'}, config_dir=tmp_path)
    assert cfg.max_width == 160


@requires_tomllib
def test_toml_overrides_default(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nmax_width = 200\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.max_width == 200


def test_default_when_nothing_set(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.max_width == 140
    assert cfg.full_width is False
    assert cfg.soft_limit == 150_000
    assert cfg.token_window == 60.0
    assert cfg.theme == 'claude-dark'
    assert cfg.bg_shift == 'warm'
    assert cfg.errors == ()


# 4.2 Alias resolution + canonical-wins

def test_legacy_token_window_alias_used_alone(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'STATUSLINE_TOKEN_WINDOW': '30'}, config_dir=tmp_path)
    assert cfg.token_window == 30.0


def test_canonical_token_window_beats_legacy_alias(tmp_path: Path) -> None:
    cfg = config.Config.load(
        env={'YAS_TOKEN_WINDOW': '45', 'STATUSLINE_TOKEN_WINDOW': '30'},
        config_dir=tmp_path,
    )
    assert cfg.token_window == 45.0


def test_legacy_theme_alias_used_alone(tmp_path: Path) -> None:
    cfg = config.Config.load(
        env={'CLAUDE_STATUSLINE_THEME': 'claude-light'}, config_dir=tmp_path,
    )
    assert cfg.theme == 'claude-light'


def test_canonical_theme_beats_legacy_alias(tmp_path: Path) -> None:
    cfg = config.Config.load(
        env={'YAS_THEME': 'catppuccin-mocha',
             'CLAUDE_STATUSLINE_THEME': 'claude-light'},
        config_dir=tmp_path,
    )
    assert cfg.theme == 'catppuccin-mocha'


def test_cli_theme_beats_env(tmp_path: Path) -> None:
    cfg = config.Config.load(
        env={'YAS_THEME': 'catppuccin-mocha'},
        config_dir=tmp_path,
        argv=['--theme=catppuccin-latte'],
    )
    assert cfg.theme == 'catppuccin-latte'


# 4.3 Per-knob validation / fallback + error recording

@requires_tomllib
def test_invalid_toml_knob_falls_back_and_records_error(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text(
        '[layout]\nmax_width = "banana"\n[tokens]\nsoft_limit = 1000000\n'
    )
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.max_width == 140              # invalid → default
    assert cfg.soft_limit == 1_000_000       # valid sibling still applies
    assert 'max_width' in cfg.errors
    assert 'soft_limit' not in cfg.errors


@requires_tomllib
def test_out_of_range_toml_soft_limit(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[tokens]\nsoft_limit = -5\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.soft_limit == 150_000
    assert 'soft_limit' in cfg.errors


@requires_tomllib
def test_unknown_enum_bg_shift(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[appearance]\nbg_shift = "purple"\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.bg_shift == 'warm'
    assert 'bg_shift' in cfg.errors


def test_invalid_env_value_records_no_error(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_MAX_WIDTH': 'banana'}, config_dir=tmp_path)
    assert cfg.max_width == 140
    assert 'max_width' not in cfg.errors      # env rejection is debug-only
    assert any('max_width' in line for line in cfg.debug_lines)


@requires_tomllib
def test_toml_full_width_must_be_real_bool(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nfull_width = "yes"\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.full_width is False
    assert 'full_width' in cfg.errors


@requires_tomllib
def test_toml_full_width_true(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nfull_width = true\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.full_width is True


def test_env_full_width_any_nonempty_is_true(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_FULL_WIDTH': '0'}, config_dir=tmp_path)
    assert cfg.full_width is True


# 4.4 Broken TOML + unknown keys

@requires_tomllib
def test_broken_toml_file_ignored_with_parse_error(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout\nmax_width = 200')  # missing ]
    cfg = config.Config.load(env={'YAS_SOFT_LIMIT': '1000000'}, config_dir=tmp_path)
    assert cfg.max_width == 140              # toml dropped entirely
    assert cfg.soft_limit == 1_000_000       # env still applies
    assert 'yas.toml: parse error' in cfg.errors


@requires_tomllib
def test_unknown_keys_and_sections_ignored(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text(
        '[layout]\nmax_width = 175\nbogus_key = 1\n'
        '[nonsense]\nfoo = "bar"\n'
    )
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.max_width == 175
    assert cfg.errors == ()


# 4.5 Python-3.10 degrade (tomllib is None)

def test_python310_tomllib_none_skips_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(config, 'tomllib', None)
    (tmp_path / 'yas.toml').write_text('[layout]\nmax_width = 200\n')
    cfg = config.Config.load(env={'YAS_SOFT_LIMIT': '1000000'}, config_dir=tmp_path)
    assert cfg.max_width == 140              # toml skipped → default
    assert cfg.soft_limit == 1_000_000       # env still applies
    assert cfg.errors == ()                  # silent skip, no parse error


# 4.6 soft_limit env cases (folds PR #32)

def test_soft_limit_default(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.soft_limit == 150_000


def test_soft_limit_env_1m(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_SOFT_LIMIT': '1000000'}, config_dir=tmp_path)
    assert cfg.soft_limit == 1_000_000


def test_soft_limit_env_empty_string_falls_back(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_SOFT_LIMIT': ''}, config_dir=tmp_path)
    assert cfg.soft_limit == 150_000


# 4.6a soft_limit_for: per-model matching

@requires_tomllib
def test_soft_limit_for_longest_match_wins(tmp_path: Path) -> None:
    # Longest substring match wins: "opus-4-8" (8 chars) beats "opus" (4).
    (tmp_path / 'yas.toml').write_text(
        '[[tokens.model]]\nmatch = "opus"\nsoft_limit = 200000\n'
        '[[tokens.model]]\nmatch = "opus-4-8"\nsoft_limit = 1000000\n'
    )
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.soft_limit_for('claude-opus-4-8[1m]',
                              'Opus 4.8 (1M context)') == 1_000_000


@requires_tomllib
def test_soft_limit_for_matches_display_name(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text(
        '[[tokens.model]]\nmatch = "1m context"\nsoft_limit = 1000000\n'
    )
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.soft_limit_for('claude-opus-4-8',
                              'Opus 4.8 (1M context)') == 1_000_000


@requires_tomllib
def test_soft_limit_for_falls_back_to_global(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text(
        '[tokens]\nsoft_limit = 175000\n'
        '[[tokens.model]]\nmatch = "opus"\nsoft_limit = 1000000\n'
    )
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.soft_limit_for('claude-sonnet-4-6', 'Sonnet 4.6') == 175_000


@requires_tomllib
def test_soft_limit_for_tie_break_file_order(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text(
        '[[tokens.model]]\nmatch = "opus"\nsoft_limit = 111111\n'
        '[[tokens.model]]\nmatch = "us-4"\nsoft_limit = 222222\n'
    )
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    # both "opus" and "us-4" have length 4 and match the id; earliest wins
    assert cfg.soft_limit_for('claude-opus-4-8', 'Opus 4.8') == 111_111


@requires_tomllib
def test_soft_limit_for_per_model_beats_env(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text(
        '[[tokens.model]]\nmatch = "1m"\nsoft_limit = 1000000\n'
    )
    cfg = config.Config.load(env={'YAS_SOFT_LIMIT': '200000'}, config_dir=tmp_path)
    assert cfg.soft_limit == 200_000  # global from env
    # specificity beats source precedence for a matching model
    assert cfg.soft_limit_for('claude-opus-4-8[1m]',
                              'Opus 4.8 (1M context)') == 1_000_000


# 4.6b Malformed [[tokens.model]] entries

@requires_tomllib
def test_malformed_model_entries_dropped_valid_kept(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text(
        '[[tokens.model]]\nmatch = ""\nsoft_limit = 500000\n'        # idx 0: empty match
        '[[tokens.model]]\nsoft_limit = 500000\n'                    # idx 1: missing match
        '[[tokens.model]]\nmatch = "opus"\nsoft_limit = "big"\n'     # idx 2: non-int limit
        '[[tokens.model]]\nmatch = "sonnet"\nsoft_limit = -1\n'      # idx 3: <= 0
        '[[tokens.model]]\nmatch = "1m"\nsoft_limit = 1000000\n'     # idx 4: valid
    )
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.soft_limit_models == (('1m', 1_000_000),)
    for i in (0, 1, 2, 3):
        assert f'tokens.model[{i}]' in cfg.errors
    assert 'tokens.model[4]' not in cfg.errors
    assert cfg.soft_limit_for('claude-opus-4-8[1m]', '') == 1_000_000


# 4.7 Error row

def test_append_error_row_noop_on_clean_config() -> None:
    cfg = config.Config()  # no errors
    r = renderer_mod.Renderer(bg_shift='warm', theme=CLAUDE_DARK)
    rows = [RowSpec('content', content='x'), RowSpec('bottom_border')]
    before = list(rows)
    append_error_row(rows, cfg, 80, r)
    assert rows == before


def test_append_error_row_inserts_warning(strip_ansi: Callable[[str], str]) -> None:
    cfg = config.Config(errors=('max_width', 'bg_shift'))
    r = renderer_mod.Renderer(bg_shift='warm', theme=CLAUDE_DARK)
    rows = [
        RowSpec('content', content='body'),
        RowSpec('bottom_border', ups=(3, 10)),
    ]
    append_error_row(rows, cfg, 80, r)
    # bottom border popped, then separator_dim + content + bottom_border appended
    assert [row.kind for row in rows] == [
        'content', 'separator_dim', 'content', 'bottom_border',
    ]
    sep = rows[1]
    assert sep.ups == (3, 10)  # elbows shifted up onto the dim separator
    warn = strip_ansi(rows[2].content)
    assert GLYPH_CONFIG_WARN in warn
    assert 'yas.toml: 2 values ignored (max_width, bg_shift)' in warn


def test_append_error_row_truncates_narrow(strip_ansi: Callable[[str], str]) -> None:
    cfg = config.Config(errors=tuple(f'knob_{i}_long_name' for i in range(8)))
    r = renderer_mod.Renderer(bg_shift='warm', theme=CLAUDE_DARK)
    width = 50
    rows = [RowSpec('content', content='x'), RowSpec('bottom_border')]
    append_error_row(rows, cfg, width, r)
    content = strip_ansi(rows[2].content)
    assert _visible_width(content) <= width - 4
    assert content.endswith('…')


def test_render_with_errors_keeps_box_integrity(
    monkeypatch: pytest.MonkeyPatch, strip_ansi: Callable[[str], str],
) -> None:
    info = json.loads(SESSION.read_text())
    cfg = config.Config(errors=tuple(f'knob_{i}_long_name' for i in range(6)))
    monkeypatch.setattr(config.Config, 'load', classmethod(lambda cls, **kw: cfg))
    width = 50
    out = app.render(info, width)
    lines = [strip_ansi(ln) for ln in out.split('\n') if ln.strip()]
    widths = {_visible_width(ln) for ln in lines}
    assert len(widths) == 1, f'box rows have mismatched widths: {widths}'
    warn_lines = [ln for ln in lines if GLYPH_CONFIG_WARN in ln]
    assert len(warn_lines) == 1


def test_render_clean_config_no_warning(
    monkeypatch: pytest.MonkeyPatch, strip_ansi: Callable[[str], str],
) -> None:
    info = json.loads(SESSION.read_text())
    cfg = config.Config()
    monkeypatch.setattr(config.Config, 'load', classmethod(lambda cls, **kw: cfg))
    out = app.render(info, 50)
    lines = [strip_ansi(ln) for ln in out.split('\n') if ln.strip()]
    assert all(GLYPH_CONFIG_WARN not in ln for ln in lines)
