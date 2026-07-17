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

import importlib.util
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
    importlib.util.find_spec('tomllib') is None,
    reason='yas.toml parsing requires tomllib (Python 3.11+)',
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
    assert cfg.glyph_mode == 'nerdfont'
    assert cfg.single_width is False
    assert cfg.show_day_stats is True
    assert cfg.show_render_time is False
    assert cfg.show_tool_uses is True
    assert cfg.justify is False
    assert cfg.labels is False
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
        env={'YAS_THEME': 'dracula',
             'CLAUDE_STATUSLINE_THEME': 'claude-light'},
        config_dir=tmp_path,
    )
    assert cfg.theme == 'dracula'


def test_cli_theme_beats_env(tmp_path: Path) -> None:
    cfg = config.Config.load(
        env={'YAS_THEME': 'dracula'},
        config_dir=tmp_path,
        argv=['--theme=nord'],
    )
    assert cfg.theme == 'nord'


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


def test_env_full_width_truthy_values(tmp_path: Path) -> None:
    for val in ('1', 'true', 'True', 'TRUE'):
        cfg = config.Config.load(env={'YAS_FULL_WIDTH': val}, config_dir=tmp_path)
        assert cfg.full_width is True, f'expected True for YAS_FULL_WIDTH={val!r}'


def test_env_full_width_falsy_values(tmp_path: Path) -> None:
    for val in ('0', 'false', 'False', 'FALSE'):
        cfg = config.Config.load(env={'YAS_FULL_WIDTH': val}, config_dir=tmp_path)
        assert cfg.full_width is False, f'expected False for YAS_FULL_WIDTH={val!r}'


def test_env_full_width_invalid_falls_through_to_default(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_FULL_WIDTH': 'yes'}, config_dir=tmp_path)
    assert cfg.full_width is False  # invalid env value → default


@requires_tomllib
def test_env_full_width_zero_overrides_toml_true(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nfull_width = true\n')
    cfg = config.Config.load(env={'YAS_FULL_WIDTH': '0'}, config_dir=tmp_path)
    assert cfg.full_width is False


# show_render_time (bottom-right render-time annotation; off by default)

@requires_tomllib
def test_toml_show_render_time_true(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nshow_render_time = true\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.show_render_time is True


@requires_tomllib
def test_toml_show_render_time_must_be_real_bool(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nshow_render_time = "yes"\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.show_render_time is False
    assert 'show_render_time' in cfg.errors


def test_env_show_render_time_truthy_values(tmp_path: Path) -> None:
    for val in ('1', 'true', 'TRUE'):
        cfg = config.Config.load(env={'YAS_SHOW_RENDER_TIME': val}, config_dir=tmp_path)
        assert cfg.show_render_time is True, f'expected True for YAS_SHOW_RENDER_TIME={val!r}'


def test_env_show_render_time_falsy_values(tmp_path: Path) -> None:
    for val in ('0', 'false', 'FALSE'):
        cfg = config.Config.load(env={'YAS_SHOW_RENDER_TIME': val}, config_dir=tmp_path)
        assert cfg.show_render_time is False, f'expected False for YAS_SHOW_RENDER_TIME={val!r}'


@requires_tomllib
def test_env_show_render_time_zero_overrides_toml_true(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nshow_render_time = true\n')
    cfg = config.Config.load(env={'YAS_SHOW_RENDER_TIME': '0'}, config_dir=tmp_path)
    assert cfg.show_render_time is False


# show_tool_uses (per-tool tool_use counts row, wide layout; on by default)

@requires_tomllib
def test_toml_show_tool_uses_false(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nshow_tool_uses = false\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.show_tool_uses is False


@requires_tomllib
def test_toml_show_tool_uses_must_be_real_bool(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nshow_tool_uses = "yes"\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.show_tool_uses is True  # rejected to default
    assert 'show_tool_uses' in cfg.errors


def test_env_show_tool_uses_falsy_values(tmp_path: Path) -> None:
    for val in ('0', 'false', 'FALSE'):
        cfg = config.Config.load(env={'YAS_SHOW_TOOL_USES': val}, config_dir=tmp_path)
        assert cfg.show_tool_uses is False, f'expected False for YAS_SHOW_TOOL_USES={val!r}'


def test_env_show_tool_uses_truthy_values(tmp_path: Path) -> None:
    for val in ('1', 'true', 'TRUE'):
        cfg = config.Config.load(env={'YAS_SHOW_TOOL_USES': val}, config_dir=tmp_path)
        assert cfg.show_tool_uses is True, f'expected True for YAS_SHOW_TOOL_USES={val!r}'


@requires_tomllib
def test_env_show_tool_uses_overrides_toml_false(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nshow_tool_uses = false\n')
    cfg = config.Config.load(env={'YAS_SHOW_TOOL_USES': '1'}, config_dir=tmp_path)
    assert cfg.show_tool_uses is True


# show_day_stats (seventh knob)

def test_env_show_day_stats_zero_is_false(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_SHOW_DAY_STATS': '0'}, config_dir=tmp_path)
    assert cfg.show_day_stats is False


def test_env_show_day_stats_falsy_values(tmp_path: Path) -> None:
    for val in ('0', 'false', 'False', 'no', 'NO'):
        cfg = config.Config.load(env={'YAS_SHOW_DAY_STATS': val}, config_dir=tmp_path)
        assert cfg.show_day_stats is False, f'expected False for {val!r}'


def test_env_show_day_stats_any_other_value_is_true(tmp_path: Path) -> None:
    for val in ('1', 'true', 'yes', 'banana'):
        cfg = config.Config.load(env={'YAS_SHOW_DAY_STATS': val}, config_dir=tmp_path)
        assert cfg.show_day_stats is True, f'expected True for {val!r}'


@requires_tomllib
def test_toml_show_day_stats_false(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[tokens]\nshow_day_stats = false\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.show_day_stats is False
    assert 'show_day_stats' not in cfg.errors


@requires_tomllib
def test_toml_show_day_stats_non_bool_rejected_to_default(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[tokens]\nshow_day_stats = "banana"\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.show_day_stats is True  # default
    assert 'show_day_stats' in cfg.errors


@requires_tomllib
def test_env_show_day_stats_beats_toml(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[tokens]\nshow_day_stats = true\n')
    cfg = config.Config.load(env={'YAS_SHOW_DAY_STATS': '0'}, config_dir=tmp_path)
    assert cfg.show_day_stats is False


@requires_tomllib
def test_env_max_width_respected_when_full_width_disabled(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nfull_width = true\n')
    cfg = config.Config.load(env={'YAS_FULL_WIDTH': '0', 'YAS_MAX_WIDTH': '40'}, config_dir=tmp_path)
    assert cfg.full_width is False
    assert cfg.max_width == 40


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


# 4.5 TOML parses via whatever parser the interpreter provides

def test_toml_loads_via_available_parser(tmp_path: Path) -> None:
    # _load_toml parses a valid yas.toml using whatever parser the interpreter
    # provides (stdlib tomllib on 3.11+, the tomli backport on 3.10). A parser
    # is guaranteed on every supported interpreter — pyproject declares
    # tomli>=2.0 for python_version < '3.11' — so this test runs unguarded and
    # exercises the real parser selection in config._load_toml on whatever
    # interpreter runs it (3.10 -> tomli, 3.11+ -> stdlib).
    (tmp_path / 'yas.toml').write_text('[layout]\nmax_width = 200\n')
    cfg = config.Config.load(env={'YAS_SOFT_LIMIT': '1000000'}, config_dir=tmp_path)
    assert cfg.max_width == 200              # toml honored via the available parser
    assert cfg.soft_limit == 1_000_000       # env still applies
    assert cfg.errors == ()                  # parsed cleanly, no error


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


# 4.4 glyph_mode resolution (CLI → env → toml → default nerdfont)

def test_env_selects_glyph_mode(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_GLYPH_MODE': 'ascii'}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'ascii'


def test_env_selects_github_glyph_mode(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_GLYPH_MODE': 'github'}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'github'


def test_env_github_glyph_mode_strips_and_lowercases(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_GLYPH_MODE': ' GitHub '}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'github'


@requires_tomllib
def test_toml_selects_github_glyph_mode(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[appearance.glyphs]\nmode = "github"\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'github'


def test_glyph_mode_default_is_nerdfont(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'nerdfont'


@requires_tomllib
def test_cli_glyph_mode_beats_env_and_toml(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[appearance.glyphs]\nmode = "nerdfont"\n')
    cfg = config.Config.load(
        env={'YAS_GLYPH_MODE': 'ascii'},
        config_dir=tmp_path,
        argv=['--glyph-mode', 'unicode'],
    )
    assert cfg.glyph_mode == 'unicode'


@requires_tomllib
def test_toml_selects_glyph_mode(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[appearance.glyphs]\nmode = "unicode"\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'unicode'


def test_env_glyph_mode_case_insensitive(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_GLYPH_MODE': 'ASCII'}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'ascii'


def test_invalid_env_glyph_mode_falls_back_and_records_debug(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_GLYPH_MODE': 'fancy'}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'nerdfont'
    assert 'glyph_mode' not in cfg.errors      # env rejection is debug-only
    assert any('glyph_mode' in line for line in cfg.debug_lines)


def test_singlewidth_no_longer_a_valid_mode(tmp_path: Path) -> None:
    # singlewidth was a mode; now it's a separate boolean. As a mode value it's
    # rejected and falls back to the default.
    cfg = config.Config.load(env={'YAS_GLYPH_MODE': 'singlewidth'}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'nerdfont'
    assert any('glyph_mode' in line for line in cfg.debug_lines)


@requires_tomllib
def test_invalid_toml_glyph_mode_falls_back_and_records_error(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[appearance.glyphs]\nmode = "fancy"\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'nerdfont'
    assert 'glyph_mode' in cfg.errors


# 4.4a single_width resolution (CLI → env → toml → default false), orthogonal to mode

def test_single_width_default_is_false(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.single_width is False


def test_env_single_width_truthy_values(tmp_path: Path) -> None:
    for val in ('1', 'true', 'True', 'TRUE'):
        cfg = config.Config.load(env={'YAS_GLYPH_SINGLE_WIDTH': val}, config_dir=tmp_path)
        assert cfg.single_width is True, f'expected True for {val!r}'


def test_env_single_width_falsy_values(tmp_path: Path) -> None:
    for val in ('0', 'false', 'False', 'FALSE'):
        cfg = config.Config.load(env={'YAS_GLYPH_SINGLE_WIDTH': val}, config_dir=tmp_path)
        assert cfg.single_width is False, f'expected False for {val!r}'


def test_cli_single_width_equals_form(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path, argv=['--glyph-single-width=true'])
    assert cfg.single_width is True


def test_cli_single_width_space_form(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path, argv=['--glyph-single-width', 'true'])
    assert cfg.single_width is True


@requires_tomllib
def test_toml_single_width_in_glyphs_subtable(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[appearance.glyphs]\nsingle_width = true\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.single_width is True


@requires_tomllib
def test_cli_single_width_beats_env_beats_toml(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[appearance.glyphs]\nsingle_width = false\n')
    # env beats toml
    cfg = config.Config.load(env={'YAS_GLYPH_SINGLE_WIDTH': 'true'}, config_dir=tmp_path)
    assert cfg.single_width is True
    # cli beats env
    cfg = config.Config.load(
        env={'YAS_GLYPH_SINGLE_WIDTH': 'true'},
        config_dir=tmp_path,
        argv=['--glyph-single-width=false'],
    )
    assert cfg.single_width is False


@requires_tomllib
def test_mode_and_single_width_combine_from_subtable(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text(
        '[appearance.glyphs]\nmode = "unicode"\nsingle_width = true\n'
    )
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'unicode'
    assert cfg.single_width is True


@requires_tomllib
def test_glyph_keys_outside_subtable_ignored(tmp_path: Path) -> None:
    # The knobs now live under [appearance.glyphs]; a bare [appearance].mode or
    # .single_width is no longer read — defaults apply, no error recorded.
    (tmp_path / 'yas.toml').write_text(
        '[appearance]\nmode = "ascii"\nsingle_width = true\n'
    )
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.glyph_mode == 'nerdfont'
    assert cfg.single_width is False
    assert 'glyph_mode' not in cfg.errors
    assert 'single_width' not in cfg.errors


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


# justify knob (task 4.1)

def test_justify_default_is_false(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.justify is False


def test_env_yas_justify_1_enables(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_JUSTIFY': '1'}, config_dir=tmp_path)
    assert cfg.justify is True


def test_env_yas_justify_0_disables(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_JUSTIFY': '0'}, config_dir=tmp_path)
    assert cfg.justify is False


def test_env_yas_justify_invalid_falls_back_to_false(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_JUSTIFY': 'yes'}, config_dir=tmp_path)
    assert cfg.justify is False


@requires_tomllib
def test_toml_layout_justify_true(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\njustify = true\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.justify is True


@requires_tomllib
def test_env_justify_overrides_toml(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\njustify = true\n')
    cfg = config.Config.load(env={'YAS_JUSTIFY': '0'}, config_dir=tmp_path)
    assert cfg.justify is False


# labels knob (section 1)

def test_labels_default_is_false(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.labels is False


@requires_tomllib
def test_toml_layout_labels_true(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nlabels = true\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.labels is True


@requires_tomllib
def test_env_labels_overrides_toml(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nlabels = true\n')
    cfg = config.Config.load(env={'YAS_LABELS': '0'}, config_dir=tmp_path)
    assert cfg.labels is False


def test_env_labels_invalid_falls_back_to_false(tmp_path: Path) -> None:
    cfg = config.Config.load(env={'YAS_LABELS': 'maybe'}, config_dir=tmp_path)
    assert cfg.labels is False


# ── yas.toml.cache (marshal binary cache of the parsed dict) ──────────────────
#
# The cache lets a warm, unchanged yas.toml skip both `import tomllib` and the
# read+parse. It is a pure optimization: any miss/staleness/corruption must fall
# back silently to the live parse with the exact same (data, error) contract.

import marshal  # noqa: E402


def _no_tomllib_guard(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Make `import tomllib` blow up, so a cache hit can be proven by NOT raising.

    Returns a callable that re-imports tomllib to assert it's genuinely blocked.
    """
    real_import = __builtins__['__import__'] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == 'tomllib':
            raise AssertionError('tomllib was imported on a warm cache hit')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr('builtins.__import__', fake_import)

    def assert_blocked() -> None:
        with pytest.raises(AssertionError):
            __import__('tomllib')

    return assert_blocked


@requires_tomllib
def test_cache_written_on_first_parse(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nmax_width = 200\n')
    assert not (tmp_path / 'yas.toml.cache').exists()
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.max_width == 200
    assert (tmp_path / 'yas.toml.cache').exists()


@requires_tomllib
def test_warm_cache_hit_skips_tomllib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / 'yas.toml').write_text('[layout]\nmax_width = 200\n')
    # First load populates the cache (tomllib allowed here).
    config.Config.load(env={}, config_dir=tmp_path)
    # Now ban tomllib: a correct warm hit must not import it.
    assert_blocked = _no_tomllib_guard(monkeypatch)
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.max_width == 200  # value came from the cache, not a reparse
    assert_blocked()


@requires_tomllib
def test_cache_invalidated_on_mtime_change(tmp_path: Path) -> None:
    toml = tmp_path / 'yas.toml'
    toml.write_text('[layout]\nmax_width = 200\n')
    config.Config.load(env={}, config_dir=tmp_path)  # warm the cache
    # Rewrite with new content; bump mtime far enough that ns granularity differs.
    toml.write_text('[layout]\nmax_width = 250\n')
    import os
    st = toml.stat()
    os.utime(toml, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.max_width == 250  # stale cache ignored, live reparse


@requires_tomllib
def test_cache_invalidated_on_backwards_mtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / 'yas.toml'
    toml.write_text('[layout]\nmax_width = 200\n')
    config.Config.load(env={}, config_dir=tmp_path)  # warm
    # Simulate a restore/checkout: same size, mtime moves BACKWARDS.
    toml.write_text('[layout]\nmax_width = 250\n')  # same byte length
    import os
    st = toml.stat()
    os.utime(toml, ns=(st.st_atime_ns, st.st_mtime_ns - 5_000_000_000))
    # A naive "older-than" check would wrongly trust the cache; ANY inequality
    # must reparse, so tomllib MUST be imported here.
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.max_width == 250


@requires_tomllib
def test_corrupt_cache_falls_back_to_live_parse(tmp_path: Path) -> None:
    toml = tmp_path / 'yas.toml'
    toml.write_text('[layout]\nmax_width = 200\n')
    (tmp_path / 'yas.toml.cache').write_bytes(b'\x00not-valid-marshal\xff')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.max_width == 200  # corruption swallowed, parsed live
    assert not cfg.errors  # corruption is NOT surfaced as a parse error
    # The bad cache should have been overwritten with a valid one.
    assert marshal.loads((tmp_path / 'yas.toml.cache').read_bytes())[0] == config.CACHE_VERSION


@requires_tomllib
def test_stale_version_cache_reparsed(tmp_path: Path) -> None:
    toml = tmp_path / 'yas.toml'
    toml.write_text('[layout]\nmax_width = 200\n')
    st = toml.stat()
    bad = marshal.dumps((config.CACHE_VERSION + 99, st.st_mtime_ns, st.st_size,
                         {'layout': {'max_width': 999}}))
    (tmp_path / 'yas.toml.cache').write_bytes(bad)
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.max_width == 200  # version mismatch → reparse from source


@requires_tomllib
def test_parse_error_writes_no_cache(tmp_path: Path) -> None:
    (tmp_path / 'yas.toml').write_text('this is = = not toml\n')
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert any('parse error' in e for e in cfg.errors)
    assert not (tmp_path / 'yas.toml.cache').exists()  # no cache for a bad parse


def test_missing_toml_writes_no_cache(tmp_path: Path) -> None:
    cfg = config.Config.load(env={}, config_dir=tmp_path)
    assert cfg.errors == ()
    assert not (tmp_path / 'yas.toml.cache').exists()


@requires_tomllib
def test_readonly_dir_cache_write_swallowed(tmp_path: Path) -> None:
    import os
    toml = tmp_path / 'yas.toml'
    toml.write_text('[layout]\nmax_width = 200\n')
    os.chmod(tmp_path, 0o500)  # read+exec, no write
    try:
        cfg = config.Config.load(env={}, config_dir=tmp_path)
        assert cfg.max_width == 200  # parse still works; write failure swallowed
        assert cfg.errors == ()
    finally:
        os.chmod(tmp_path, 0o700)
