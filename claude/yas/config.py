"""Layered configuration for yet-another-statusline.

Every configurable knob resolves through one fixed chain:
  CLI flag  →  canonical YAS_* env  →  legacy-alias env  →  yas.toml  →  default

A higher-precedence source that is present and valid wins; an absent or
invalid source falls through to the next. Only yas.toml-sourced rejections are
surfaced in the visible error row (the row is titled "yas.toml"); every
rejection (any source) is recorded in debug_lines for YAS_DEBUG stderr output.
"""

from __future__ import annotations

import json
import os
try:
    import tomllib
except ImportError:  # Python 3.10 ships no stdlib tomllib; yas.toml is skipped.
    tomllib = None  # type: ignore[assignment]
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from yas.constants import (
    CLAUDE_DIR,
    DEFAULT_JUSTIFY,
    DEFAULT_MAX_WIDTH,
    DEFAULT_SOFT_LIMIT,
    DEFAULT_TOKEN_WINDOW,
    DEFAULT_THEME,
    DEFAULT_SHOW_DAY_STATS,
)
from yas.themes import THEMES

if TYPE_CHECKING:
    pass


_T = TypeVar('_T')


def _parse_pos_int(raw: object, origin: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise ValueError('expected an integer')
    n = int(raw)  # str/int/float ok; 'banana' raises
    if n <= 0:
        raise ValueError('must be > 0')
    return n


def _parse_pos_float(raw: object, origin: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise ValueError('expected a number')
    x = float(raw)
    if x <= 0:
        raise ValueError('must be > 0')
    return x

BOOL_ALLOWLIST = ('1', '0', 'true', 'false')

def _parse_bool(raw: object, origin: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if origin == 'cli' or origin.startswith('env'):
        v = str(raw).strip().lower()
        if v not in BOOL_ALLOWLIST:
            raise ValueError(f"expected one of {', '.join(BOOL_ALLOWLIST)}")
        return bool(json.loads(v))
    raise ValueError('expected a boolean')


def _parse_show_day_stats(raw: object, origin: str) -> bool:
    """Boolean knob with lenient env form.

    A real TOML boolean is taken as-is. From CLI/env, ``0``/``false``/``no``
    (case-insensitive) are false and any other non-empty value is true (empty
    env values are already filtered out upstream as "absent"). A non-boolean
    TOML value raises so it falls back to the default and is recorded.
    """
    if isinstance(raw, bool):
        return raw
    if origin == 'cli' or origin.startswith('env'):
        return str(raw).strip().lower() not in ('0', 'false', 'no')
    raise ValueError('expected a boolean')


def _parse_theme(raw: object, origin: str) -> str:
    name = str(raw).strip()
    if name in THEMES:
        return name
    raise ValueError(f'unknown theme {name!r}')


def _parse_bg_shift(raw: object, origin: str) -> str:
    v = str(raw).strip().lower()
    if v in ('warm', 'cool'):
        return v
    raise ValueError(f'expected warm or cool, got {v!r}')


def _env_sources(env: dict[str, str], canonical: str, *aliases: str) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for name in (canonical, *aliases):
        v = env.get(name)
        if v not in (None, ''):  # empty string env var == absent
            out.append((f'env:{name}', v))
    return out


def _resolve(
    label: str,
    sources: list[tuple[str, object]],
    parse: Callable[[object, str], _T],
    default: _T,
    errors: list[str],
    debug: list[str],
) -> _T:
    """Walk precedence sources; first that parses wins, else the default.

    Records every present-but-invalid value in ``debug``; records the knob name
    in ``errors`` only for yas.toml-sourced rejections (the visible row is
    titled "yas.toml" so env/CLI failures stay debug-only).
    """
    for origin, raw in sources:
        try:
            return parse(raw, origin)
        except (ValueError, TypeError) as e:
            debug.append(f'{label}: {origin} value {raw!r} rejected ({e})')
            if origin == 'toml' and label not in errors:
                errors.append(label)
    return default


def _legacy_theme_sources(config_dir: Path) -> list[tuple[str, object]]:
    """The deprecated ~/.claude/statusline-theme file, lowest priority."""
    try:
        name = (config_dir / 'statusline-theme').read_text().strip()
    except OSError:
        return []
    return [('legacy', name)] if name else []


def _parse_argv(argv: Sequence[str]) -> dict[str, str]:
    """Extract --theme / --bg-shift overrides from a CLI argv slice."""
    out: dict[str, str] = {}
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == '--bg-shift' and args:
            out['bg_shift'] = args.pop(0)
        elif a.startswith('--bg-shift='):
            out['bg_shift'] = a.split('=', 1)[1]
        elif a == '--theme' and args:
            out['theme'] = args.pop(0)
        elif a.startswith('--theme='):
            out['theme'] = a.split('=', 1)[1]
    return out


def _load_toml(config_dir: Path) -> tuple[dict[str, object], str | None]:
    """Read config_dir/yas.toml.

    Returns (data, error). Missing file or no tomllib (Python 3.10) → ({}, None),
    i.e. silently skipped. A parse failure → ({}, "yas.toml: parse error").
    """
    if tomllib is None:
        return {}, None
    try:
        text = (config_dir / 'yas.toml').read_text()
    except OSError:
        return {}, None  # missing file is not an error
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return {}, 'yas.toml: parse error'
    return data, None


def _parse_models(raw: object, errors: list[str], debug: list[str]) -> list[tuple[str, int]]:
    """Validate the [[tokens.model]] array into order-preserving (match, limit)."""
    out: list[tuple[str, int]] = []
    if not isinstance(raw, list):
        return out
    for i, entry in enumerate(raw):
        label = f'tokens.model[{i}]'
        if not isinstance(entry, dict):
            errors.append(label)
            debug.append(f'{label}: not a table')
            continue
        match = entry.get('match')
        limit = entry.get('soft_limit')
        if not isinstance(match, str) or not match.strip():
            errors.append(label)
            debug.append(f'{label}: missing or empty match')
            continue
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            errors.append(label)
            debug.append(f'{label}: soft_limit must be an integer > 0')
            continue
        out.append((match.strip().lower(), limit))
    return out


@dataclass(frozen=True)
class Config:
    max_width: int = DEFAULT_MAX_WIDTH
    full_width: bool = False
    justify: bool = DEFAULT_JUSTIFY
    soft_limit: int = DEFAULT_SOFT_LIMIT
    token_window: float = DEFAULT_TOKEN_WINDOW
    theme: str = DEFAULT_THEME
    bg_shift: str = 'warm'
    show_day_stats: bool = DEFAULT_SHOW_DAY_STATS
    soft_limit_models: tuple[tuple[str, int], ...] = ()
    errors: tuple[str, ...] = ()
    debug_lines: tuple[str, ...] = ()

    @classmethod
    def load(
        cls,
        env: dict[str, str] | None = None,
        config_dir: Path | None = None,
        argv: Sequence[str] | None = None,
    ) -> Config:
        if env is None:
            env = dict(os.environ)
        if config_dir is None:
            config_dir = CLAUDE_DIR
        errors: list[str] = []
        debug: list[str] = []

        toml_data, parse_err = _load_toml(config_dir)
        if parse_err:
            errors.append(parse_err)
            debug.append(parse_err)

        def _table(name: str) -> dict[str, object]:
            v = toml_data.get(name)
            return v if isinstance(v, dict) else {}

        layout, tokens, appearance = _table('layout'), _table('tokens'), _table('appearance')
        cli = _parse_argv(argv) if argv is not None else {}

        def toml_src(table: dict[str, object], key: str) -> list[tuple[str, object]]:
            return [('toml', table[key])] if key in table else []

        def cli_src(name: str) -> list[tuple[str, object]]:
            return [('cli', cli[name])] if name in cli else []

        max_width = _resolve(
            'max_width',
            _env_sources(env, 'YAS_MAX_WIDTH') + toml_src(layout, 'max_width'),
            _parse_pos_int, DEFAULT_MAX_WIDTH, errors, debug)
        full_width = _resolve(
            'full_width',
            _env_sources(env, 'YAS_FULL_WIDTH') + toml_src(layout, 'full_width'),
            _parse_bool, False, errors, debug)
        soft_limit = _resolve(
            'soft_limit',
            _env_sources(env, 'YAS_SOFT_LIMIT') + toml_src(tokens, 'soft_limit'),
            _parse_pos_int, DEFAULT_SOFT_LIMIT, errors, debug)
        token_window = _resolve(
            'token_window',
            _env_sources(env, 'YAS_TOKEN_WINDOW', 'STATUSLINE_TOKEN_WINDOW') + toml_src(tokens, 'token_window'),
            _parse_pos_float, DEFAULT_TOKEN_WINDOW, errors, debug)
        theme = _resolve(
            'theme',
            cli_src('theme')
            + _env_sources(env, 'YAS_THEME', 'CLAUDE_STATUSLINE_THEME')
            + toml_src(appearance, 'theme')
            + _legacy_theme_sources(config_dir),
            _parse_theme, DEFAULT_THEME, errors, debug)
        bg_shift = _resolve(
            'bg_shift',
            cli_src('bg_shift')
            + _env_sources(env, 'YAS_BG_SHIFT')
            + toml_src(appearance, 'bg_shift'),
            _parse_bg_shift, 'warm', errors, debug)
        show_day_stats = _resolve(
            'show_day_stats',
            _env_sources(env, 'YAS_SHOW_DAY_STATS') + toml_src(tokens, 'show_day_stats'),
            _parse_show_day_stats, DEFAULT_SHOW_DAY_STATS, errors, debug)
        justify = _resolve(
            'justify',
            _env_sources(env, 'YAS_JUSTIFY') + toml_src(layout, 'justify'),
            _parse_bool, DEFAULT_JUSTIFY, errors, debug)

        soft_limit_models = _parse_models(tokens.get('model'), errors, debug)

        return cls(
            max_width=max_width,
            full_width=full_width,
            justify=justify,
            soft_limit=soft_limit,
            token_window=token_window,
            theme=theme,
            bg_shift=bg_shift,
            show_day_stats=show_day_stats,
            soft_limit_models=tuple(soft_limit_models),
            errors=tuple(errors),
            debug_lines=tuple(debug),
        )

    def soft_limit_for(self, model_id: str, display_name: str = '') -> int:
        """Resolve the effective soft_limit for a session model.

        Each [[tokens.model]] ``match`` is a case-insensitive plain substring
        tested against the lowercased id and display_name. The longest match
        wins; ties break by file order. No match → the global soft_limit.
        """
        hay_id, hay_name = model_id.lower(), display_name.lower()
        best_key: tuple[int, int] | None = None
        best_limit = self.soft_limit
        for i, (match, limit) in enumerate(self.soft_limit_models):
            if match in hay_id or match in hay_name:
                key = (len(match), -i)  # longer wins; tie → earlier (smaller i)
                if best_key is None or key > best_key:
                    best_key, best_limit = key, limit
        return best_limit
