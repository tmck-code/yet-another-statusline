## Why

Statusline behaviour is currently configured through a scattered, inconsistently-named set of environment variables (`YAS_MAX_WIDTH`, `YAS_FULL_WIDTH`, `STATUSLINE_TOKEN_WINDOW`, `CLAUDE_STATUSLINE_THEME`) plus one hardcoded constant (`SOFT_LIMIT = 150_000`). There is no persistent, file-based way to customise the statusline, the prefixes are a soup (`YAS_*` / `STATUSLINE_*` / `CLAUDE_STATUSLINE_*`), and several knobs users have asked for in issues/PRs (e.g. `soft_limit` for 1M-context models, PR #32) have no home. Users want to set these once per machine and forget them.

## What Changes

- Introduce a `yas.toml` config file read from `CLAUDE_CONFIG_DIR` (default `~/.claude/`), parsed with a sectioned schema (`[layout]`, `[tokens]`, `[appearance]`).
- Add a single, frozen `Config` dataclass with one `Config.load()` that resolves every knob through one precedence chain — **CLI flag → canonical `YAS_*` env → legacy-alias env → `yas.toml` → built-in default** — replacing the scattered module-level `os.environ.get` reads.
- Expose six knobs: `max_width`, `full_width`, `soft_limit`, `token_window`, `theme`, `bg_shift`.
- Make `soft_limit` configurable **globally and per-model**: a global `[tokens].soft_limit` default plus an optional `[[tokens.model]]` array of `{ match, soft_limit }` overrides. `match` is a case-insensitive plain substring tested against the model `id`/`display_name` (longest match wins), so users can target 1M-context variants distinctly from the family by giving the variant a longer, more-specific match (`match = "opus-4-8[1m]"` outranks `match = "opus"`). A matching per-model override beats the global value from any source — the single documented exception to env > toml (per-model is toml-only; there is no per-model env var).
- Standardise canonical env names on the `YAS_*` prefix (new: `YAS_SOFT_LIMIT`, `YAS_TOKEN_WINDOW`, `YAS_THEME`, `YAS_BG_SHIFT`); keep `STATUSLINE_TOKEN_WINDOW` and `CLAUDE_STATUSLINE_THEME` as **deprecated aliases** (canonical wins on conflict). No existing env var stops working.
- Parse TOML via stdlib `tomllib` with a graceful try-import; on Python 3.10 (no `tomllib`) the file is silently skipped and env + defaults still apply. The script stays zero-dependency.
- Never crash on bad config: malformed TOML → ignore the whole file; a bad/out-of-range/wrong-type value → drop only that knob to its default. When any value is rejected, append one compact, width-truncated **error row** at the bottom of the box naming the rejected knobs; full per-value reasons go to stderr only when `YAS_DEBUG` is set.
- Ship a commented `yas.example.toml` (every knob at its default) and document the full knob/env/toml/default/precedence matrix in the README and `CONTEXT.md`. `yas.toml` is **not** auto-written — absence means all defaults.
- Layout breakpoints (`narrow`/`medium`/`min` width) remain hardcoded and are intentionally **not** configurable (hand-tuned column math).

## Capabilities

### New Capabilities
- `statusline-config`: Layered configuration system for the statusline — the `Config` dataclass, the precedence chain, the `yas.toml` schema and parsing, per-knob validation with fail-safe fallback, the visible config-error row, and the canonical/alias env-var surface.

### Modified Capabilities
<!-- No existing specs in openspec/specs/; all behaviour is captured under the new statusline-config capability. -->

## Impact

- **Code**: `claude/statusline_command.py` — new `Config` dataclass + `Config.load()`; module constants (`MAX_WIDTH`, `SOFT_LIMIT` = resolved *global*, token window, theme/bg_shift resolution) re-sourced from the singleton; a `Config.soft_limit_for(model_name)` resolver threaded from `render()` through `build_narrow/medium/wide` into the `context_line` helpers (which read module `SOFT_LIMIT` today); `render()` appends the error row when `cfg.errors` is non-empty; `resolve_theme` folded into the precedence chain.
- **Tests**: new `test/test_config.py` (precedence, alias resolution, per-knob fallback, error collection, 3.10 no-`tomllib` degrade path); PR #32's three `soft_limit` cases folded in; existing `test_context_line.py` stays green.
- **Docs**: README knob matrix, `CONTEXT.md` config section + `⚠` error-row glossary entry, new `yas.example.toml`.
- **Dependencies**: none added (stdlib `tomllib` only); `requires-python` stays `>=3.10`.
- **Coordination**: PR #32 (`YAS_SOFT_LIMIT`) is merged first; this change then migrates that constant into `Config`.
- **Sibling tools**: `claude/mon.py` imports `render()` and is unaffected (it passes its own theme); the import-time singleton applies transparently.
