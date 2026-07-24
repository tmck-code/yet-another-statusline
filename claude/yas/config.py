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
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from yas.constants import (
    CLAUDE_DIR,
    DEFAULT_CONTEXT_LABELS,
    DEFAULT_CONTEXT_STATE,
    DEFAULT_CONTEXT_THRESHOLDS,
    DEFAULT_JUSTIFY,
    DEFAULT_LABELS,
    DEFAULT_MAX_WIDTH,
    DEFAULT_SOFT_LIMIT,
    DEFAULT_TOKEN_WINDOW,
    DEFAULT_THEME,
    DEFAULT_SHOW_DAY_STATS,
    DEFAULT_SHOW_TOOL_USES,
    DEFAULT_SUBAGENT_TREE,
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


def _parse_glyph_mode(raw: object, origin: str) -> str:
    v = str(raw).strip().lower()
    if v in ('nerdfont', 'ascii', 'unicode', 'github'):
        return v
    raise ValueError(f'expected one of nerdfont, ascii, unicode, github, got {v!r}')


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
        elif a == '--glyph-mode' and args:
            out['glyph_mode'] = args.pop(0)
        elif a.startswith('--glyph-mode='):
            out['glyph_mode'] = a.split('=', 1)[1]
        elif a == '--glyph-single-width' and args:
            out['single_width'] = args.pop(0)
        elif a.startswith('--glyph-single-width='):
            out['single_width'] = a.split('=', 1)[1]
    return out


# Bump to invalidate every on-disk yas.toml.cache (e.g. if the cached shape ever
# changes). A stamp mismatch — including this version — silently reparses.
CACHE_VERSION = 1


def _read_toml_cache(cache_path: Path, mtime_ns: int, size: int) -> dict[str, object] | None:
    """Return the cached parsed dict iff fresh, else None.

    The cache is keyed on (CACHE_VERSION, mtime_ns, size) of yas.toml. ANY
    mismatch — stale, a backwards mtime jump (restore/checkout), or a version
    bump — is treated as a miss. A corrupt/unreadable cache or a marshal error
    is swallowed and also reported as a miss; the cache is a pure optimization,
    so correctness never depends on it. A hit lets the caller skip importing
    tomllib and re-reading/parsing yas.toml entirely.
    """
    import marshal  # builtin: zero marginal import cost
    try:
        blob = cache_path.read_bytes()
        cached = marshal.loads(blob)
    except (OSError, ValueError, EOFError, TypeError):
        return None
    if (isinstance(cached, tuple) and len(cached) == 4
            and cached[0] == CACHE_VERSION
            and cached[1] == mtime_ns
            and cached[2] == size
            and isinstance(cached[3], dict)):
        return cached[3]
    return None


def _write_toml_cache(cache_path: Path, mtime_ns: int, size: int, data: dict[str, object]) -> None:
    """Atomically write the parsed dict to the cache, swallowing any failure.

    Writes to a temp file in the same dir then os.replace()s it into place so a
    concurrent reader never sees a torn file. A read-only dir, a marshal error
    (shouldn't happen — TOML primitives are all marshal-safe), or any OSError is
    swallowed: a failed write just means the next run reparses.
    """
    import marshal
    tmp = cache_path.with_name(f'{cache_path.name}.{os.getpid()}.tmp')
    try:
        blob = marshal.dumps((CACHE_VERSION, mtime_ns, size, data))
        with open(tmp, 'wb') as fh:
            fh.write(blob)
        os.replace(tmp, cache_path)
    except (OSError, ValueError, TypeError):
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _load_toml(config_dir: Path) -> tuple[dict[str, object], str | None]:
    """Read config_dir/yas.toml.

    Returns (data, error). Missing file → ({}, None), i.e. silently skipped.
    On Python 3.10 (no stdlib tomllib) the tomli backport is used instead, so
    TOML is still parsed. A parse failure → ({}, "yas.toml: parse error").

    A binary (marshal) cache of the parsed dict lives at yas.toml.cache next to
    the source. On a warm, unchanged file the dict is returned straight from the
    cache, skipping BOTH `import tomllib` and the read+parse. Any cache miss/
    staleness/corruption falls through to the live parse below, which then
    refreshes the cache.
    """
    toml_path = config_dir / 'yas.toml'
    cache_path = config_dir / 'yas.toml.cache'
    try:
        st = toml_path.stat()
    except OSError:
        return {}, None  # missing file is not an error
    mtime_ns, size = st.st_mtime_ns, st.st_size

    cached = _read_toml_cache(cache_path, mtime_ns, size)
    if cached is not None:
        return cached, None  # warm hit: tomllib never imported

    try:
        text = toml_path.read_text()
    except OSError:
        return {}, None
    # Deferred: tomllib (parser + regex tables) is imported only on a cache miss
    # when a yas.toml actually exists — warm hits and the no-config path skip it.
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # Python 3.10 — use the tomli backport
        import tomli as tomllib
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return {}, 'yas.toml: parse error'  # no cache written for a parse error
    _write_toml_cache(cache_path, mtime_ns, size, data)
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


def _as_seq(raw: object) -> list[object]:
    """Normalise a list knob to a list of items.

    A TOML array arrives as a ``list``; an env/CLI value arrives as a
    comma-separated ``str``. Anything else is rejected by the caller.
    """
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, str):
        return [s.strip() for s in raw.split(',')]
    raise ValueError('expected a list or comma-separated string')


def _parse_context_labels(raw: object, origin: str) -> tuple[str, ...]:
    """Exactly 5 non-empty label words (Smart..Dumb by default)."""
    items = [str(s).strip() for s in _as_seq(raw)]
    if len(items) != 5 or not all(items):
        raise ValueError('expected exactly 5 non-empty labels')
    return tuple(items)


def _parse_context_thresholds(raw: object, origin: str) -> tuple[int, ...]:
    """Exactly 4 strictly-ascending ints in 1..99 (band starts for levels 2-5).

    Mirrors Dumbometer's DUMBOMETER_THRESHOLDS validation.
    """
    seq = _as_seq(raw)
    if any(isinstance(x, bool) for x in seq):
        raise ValueError('expected integers')
    try:
        nums = [int(str(x).strip()) for x in seq]
    except (TypeError, ValueError):
        raise ValueError('expected integers')
    if (
        len(nums) != 4
        or not all(1 <= n <= 99 for n in nums)
        or not (nums[0] < nums[1] < nums[2] < nums[3])
    ):
        raise ValueError('expected 4 strictly ascending ints in 1..99')
    return tuple(nums)


class Config:
    __slots__ = (
        'max_width', 'full_width', 'justify', 'labels', 'soft_limit',
        'token_window', 'theme', 'bg_shift', 'glyph_mode', 'single_width',
        'show_day_stats', 'context_state', 'context_labels', 'context_thresholds',
        'show_render_time', 'show_tool_uses', 'subagent_tree', 'soft_limit_models', 'errors', 'debug_lines',
    )

    max_width:          int
    full_width:         bool
    justify:            bool
    labels:             bool
    soft_limit:         int
    token_window:       float
    theme:              str
    bg_shift:           str
    glyph_mode:         str
    single_width:       bool
    show_day_stats:     bool
    context_state:      bool
    context_labels:     tuple[str, ...]
    context_thresholds: tuple[int, ...]
    show_render_time:   bool
    show_tool_uses:     bool
    subagent_tree:      bool
    soft_limit_models:  tuple[tuple[str, int], ...]
    errors:             tuple[str, ...]
    debug_lines:        tuple[str, ...]

    def __init__(
        self,
        max_width:          int = DEFAULT_MAX_WIDTH,
        full_width:         bool = False,
        justify:            bool = DEFAULT_JUSTIFY,
        labels:             bool = DEFAULT_LABELS,
        soft_limit:         int = DEFAULT_SOFT_LIMIT,
        token_window:       float = DEFAULT_TOKEN_WINDOW,
        theme:              str = DEFAULT_THEME,
        bg_shift:           str = 'warm',
        glyph_mode:         str = 'nerdfont',
        single_width:       bool = False,
        show_day_stats:     bool = DEFAULT_SHOW_DAY_STATS,
        context_state:      bool = DEFAULT_CONTEXT_STATE,
        context_labels:     tuple[str, ...] = DEFAULT_CONTEXT_LABELS,
        context_thresholds: tuple[int, ...] = DEFAULT_CONTEXT_THRESHOLDS,
        show_render_time:   bool = False,
        show_tool_uses:     bool = DEFAULT_SHOW_TOOL_USES,
        subagent_tree:      bool = DEFAULT_SUBAGENT_TREE,
        soft_limit_models:  tuple[tuple[str, int], ...] = (),
        errors:             tuple[str, ...] = (),
        debug_lines:        tuple[str, ...] = (),
    ) -> None:
        s = object.__setattr__
        s(self, 'max_width', max_width)
        s(self, 'full_width', full_width)
        s(self, 'justify', justify)
        s(self, 'labels', labels)
        s(self, 'soft_limit', soft_limit)
        s(self, 'token_window', token_window)
        s(self, 'theme', theme)
        s(self, 'bg_shift', bg_shift)
        s(self, 'glyph_mode', glyph_mode)
        s(self, 'single_width', single_width)
        s(self, 'show_day_stats', show_day_stats)
        s(self, 'context_state', context_state)
        s(self, 'context_labels', context_labels)
        s(self, 'context_thresholds', context_thresholds)
        s(self, 'show_render_time', show_render_time)
        s(self, 'show_tool_uses', show_tool_uses)
        s(self, 'subagent_tree', subagent_tree)
        s(self, 'soft_limit_models', soft_limit_models)
        s(self, 'errors', errors)
        s(self, 'debug_lines', debug_lines)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f'cannot assign to field {name!r}')

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f'cannot delete field {name!r}')

    def __repr__(self) -> str:
        return (f'Config(max_width={self.max_width}, full_width={self.full_width}, '
                f'justify={self.justify}, labels={self.labels}, soft_limit={self.soft_limit}, '
                f'token_window={self.token_window}, theme={self.theme!r}, bg_shift={self.bg_shift!r}, '
                f'glyph_mode={self.glyph_mode!r}, single_width={self.single_width}, '
                f'show_day_stats={self.show_day_stats}, context_state={self.context_state}, '
                f'context_labels={self.context_labels!r}, context_thresholds={self.context_thresholds!r}, '
                f'show_render_time={self.show_render_time}, show_tool_uses={self.show_tool_uses}, '
                f'subagent_tree={self.subagent_tree}, '
                f'soft_limit_models={self.soft_limit_models!r}, '
                f'errors={self.errors!r}, debug_lines={self.debug_lines!r})')

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

        def _table_in(table: dict[str, object], name: str) -> dict[str, object]:
            v = table.get(name)
            return v if isinstance(v, dict) else {}

        layout, tokens, appearance = _table('layout'), _table('tokens'), _table('appearance')
        context = _table('context')
        glyphs = _table_in(appearance, 'glyphs')
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
        glyph_mode = _resolve(
            'glyph_mode',
            cli_src('glyph_mode')
            + _env_sources(env, 'YAS_GLYPH_MODE')
            + toml_src(glyphs, 'mode'),
            _parse_glyph_mode, 'nerdfont', errors, debug)
        single_width = _resolve(
            'single_width',
            cli_src('single_width')
            + _env_sources(env, 'YAS_GLYPH_SINGLE_WIDTH')
            + toml_src(glyphs, 'single_width'),
            _parse_bool, False, errors, debug)
        show_day_stats = _resolve(
            'show_day_stats',
            _env_sources(env, 'YAS_SHOW_DAY_STATS') + toml_src(tokens, 'show_day_stats'),
            _parse_show_day_stats, DEFAULT_SHOW_DAY_STATS, errors, debug)
        show_render_time = _resolve(
            'show_render_time',
            _env_sources(env, 'YAS_SHOW_RENDER_TIME') + toml_src(layout, 'show_render_time'),
            _parse_bool, False, errors, debug)
        show_tool_uses = _resolve(
            'show_tool_uses',
            _env_sources(env, 'YAS_SHOW_TOOL_USES') + toml_src(layout, 'show_tool_uses'),
            _parse_bool, DEFAULT_SHOW_TOOL_USES, errors, debug)
        subagent_tree = _resolve(
            'subagent_tree',
            _env_sources(env, 'YAS_SUBAGENT_TREE') + toml_src(layout, 'subagent_tree'),
            _parse_bool, DEFAULT_SUBAGENT_TREE, errors, debug)
        justify = _resolve(
            'justify',
            _env_sources(env, 'YAS_JUSTIFY') + toml_src(layout, 'justify'),
            _parse_bool, DEFAULT_JUSTIFY, errors, debug)
        labels = _resolve(
            'labels',
            _env_sources(env, 'YAS_LABELS') + toml_src(layout, 'labels'),
            _parse_bool, DEFAULT_LABELS, errors, debug)
        context_state = _resolve(
            'context_state',
            _env_sources(env, 'YAS_CONTEXT_STATE') + toml_src(context, 'state'),
            _parse_bool, DEFAULT_CONTEXT_STATE, errors, debug)
        context_labels = _resolve(
            'context_labels',
            _env_sources(env, 'YAS_CONTEXT_LABELS') + toml_src(context, 'labels'),
            _parse_context_labels, DEFAULT_CONTEXT_LABELS, errors, debug)
        context_thresholds = _resolve(
            'context_thresholds',
            _env_sources(env, 'YAS_CONTEXT_THRESHOLDS') + toml_src(context, 'thresholds'),
            _parse_context_thresholds, DEFAULT_CONTEXT_THRESHOLDS, errors, debug)

        soft_limit_models = _parse_models(tokens.get('model'), errors, debug)

        return cls(
            max_width=max_width,
            full_width=full_width,
            justify=justify,
            labels=labels,
            soft_limit=soft_limit,
            token_window=token_window,
            theme=theme,
            bg_shift=bg_shift,
            glyph_mode=glyph_mode,
            single_width=single_width,
            show_day_stats=show_day_stats,
            context_state=context_state,
            context_labels=context_labels,
            context_thresholds=context_thresholds,
            show_render_time=show_render_time,
            show_tool_uses=show_tool_uses,
            subagent_tree=subagent_tree,
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
