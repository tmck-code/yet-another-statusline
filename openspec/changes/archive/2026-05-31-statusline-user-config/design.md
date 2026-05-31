## Context

`claude/statusline_command.py` is a zero-dependency, stdlib-only single script (`dependencies = []`, `requires-python = ">=3.10"`) symlinked/vendored into `~/.claude/`. Configuration today is a handful of module-level constants read from `os.environ` at import time with three inconsistent prefixes (`YAS_MAX_WIDTH`, `YAS_FULL_WIDTH`, `STATUSLINE_TOKEN_WINDOW`, `CLAUDE_STATUSLINE_THEME`) plus a hardcoded `SOFT_LIMIT = 150_000`. `resolve_theme()` already implements an ad-hoc layered lookup (CLI → env → `statusline-theme` file → default). Tests exercise env handling by reloading the module via `importlib.util` (see `conftest.py` and PR #32's `test_soft_limit_env.py`). The renderer is layout-spec driven: `render()` selects `build_narrow/medium/wide`, each returns a `LayoutSpec` of `RowSpec`s, and `render_layout()` walks them. Column math is hand-tuned and silent-bug-prone.

## Goals / Non-Goals

**Goals:**
- One `Config` dataclass + one `Config.load()` owning the entire precedence chain (CLI → `YAS_*` → legacy alias → `yas.toml` → default), eliminating scattered `os.environ.get` reads.
- A sectioned `yas.toml` in `CLAUDE_CONFIG_DIR` parsed with stdlib `tomllib`, degrading silently on Python 3.10.
- Six knobs: `max_width`, `full_width`, `soft_limit`, `token_window`, `theme`, `bg_shift`.
- Never crash on bad config; per-knob fallback; one compact visible error row naming rejected knobs.
- Backward compatibility: every existing env var keeps working; existing module constants and module-reload tests keep working.
- A commented `yas.example.toml` + README/CONTEXT.md docs.

**Non-Goals:**
- Configurable layout breakpoints (narrow/medium/min width) — stays hardcoded.
- Auto-writing `yas.toml` (init does not create it; absence = defaults).
- Adding any third-party dependency or bumping `requires-python` above `>=3.10`.
- Live config reload / file watching — config is read once per render invocation.

## Decisions

**1. Single frozen `Config` dataclass, loaded at import time into a module singleton.**
`Config.load(env=os.environ, config_dir=CLAUDE_DIR, argv=None)` returns a frozen `Config` with one field per knob plus `errors: tuple[str, ...]` and `debug_lines: tuple[str, ...]`. A module-level `CONFIG = Config.load()` runs at import; `MAX_WIDTH`, `SOFT_LIMIT`, and the token-rate window are then assigned from `CONFIG` so existing call sites and module-reload tests are unchanged. *Alternative — thread Config through every `render`/`build_*` signature:* rejected as too large a blast radius for no user-visible gain. *Alternative — keep scattered constants with inline toml fallback:* rejected; duplicates precedence logic at every knob, no single schema.

**2. Per-knob resolver helper centralises precedence + validation.**
A small internal resolver takes (canonical env name, alias env name(s), toml section/key, a parse/validate callable, default) and walks the chain, appending to `errors`/`debug_lines` on a rejected non-empty value. Each knob is one declarative call. This keeps precedence identical across knobs and makes the validation table the single source of truth.

**3. `tomllib` via guarded import.**
`try: import tomllib\nexcept ImportError: tomllib = None`. `Config.load()` reads `config_dir/yas.toml`; if `tomllib is None` or the file is missing the toml layer is an empty dict. A `tomllib.TOMLDecodeError` (or any parse failure) records one error ("yas.toml: parse error") and treats the toml layer as empty. *Alternative — bump to 3.11 / vendor a parser / add `tomli`:* rejected (breaking floor / maintenance burden / breaks zero-dep).

**4. Error surfacing = compact row + `YAS_DEBUG` stderr.**
`render()` checks `CONFIG.errors`; if non-empty it appends one `RowSpec` (a new `error` content row, or a plain content row via a shared helper) above the bottom border in each `build_*`. To avoid special-casing `render_layout`, a shared `append_error_row(rows, cfg, width, r)` helper is called at the end of each builder and re-threads the bottom-border `ups`. The row text is `⚠ yas.toml: N values ignored (k1, k2, …)`, truncated via `_visible_width`. `Config.load()` writes `debug_lines` to stderr at load time only when `YAS_DEBUG` is set. *Alternative — fail loud / vanish:* rejected; a statusline that disappears over a typo is worse than defaults.

**5. `resolve_theme` and `bg_shift` fold into the chain.**
`theme` resolves CLI `--theme` → `YAS_THEME` → `CLAUDE_STATUSLINE_THEME` → `[appearance].theme` → `statusline-theme` file (kept as a lowest-priority legacy fallback) → `CLAUDE_DARK`. `bg_shift` resolves CLI `--bg-shift` → `YAS_BG_SHIFT` → `[appearance].bg_shift` → `warm`. CLI parsing stays in `main()` and is passed into `Config.load(argv=...)` (or applied as an override after load) so CLI keeps top precedence.

**6. PR #32 merged first.**
The `YAS_SOFT_LIMIT` one-liner lands on `main` first (done — merge `99123d9`); this change then replaces that line with the `Config`-sourced *global* `soft_limit` and folds #32's three test cases (default / override / empty-string) into `test_config.py`.

**7. `soft_limit` is global-or-per-model; resolution is render-time and two-tier.**
`Config` carries `soft_limit: int` (resolved global via `YAS_SOFT_LIMIT` → `[tokens].soft_limit` → `150_000`) and `soft_limit_models: tuple[(match: str, limit: int), ...]` (validated, order-preserving) parsed from the `[[tokens.model]]` array. `Config.soft_limit_for(model_name)` lowercases the session's `id`+`display_name`, keeps every entry whose `match` is a substring of either, returns the *longest* match's limit (ties → first in file order), else the global. `match` is a literal case-insensitive substring — no glob/regex, so there is no pattern-compile error surface. Because the session model is only known at render time, `SOFT_LIMIT` cannot be a single static module constant for the render paths: `render()` computes `eff = CONFIG.soft_limit_for(session.model_name)` once and threads the int through `build_narrow/medium/wide` into `context_line`/`context_line_compact` (which read module `SOFT_LIMIT` today); module `SOFT_LIMIT` is retained as the resolved global for back-compat and reload tests. **Per-model toml beats the global env** (`YAS_SOFT_LIMIT`): specificity wins over source precedence — the single documented carve-out to the blanket env > toml rule, since no sane per-model env var exists. *Alternatives:* family-bucket keying (opus/sonnet/haiku) — rejected, `model_key()` collapses the `[1m]` variant that motivates the feature; exact-id keying — rejected, brittle with no family fallback; auto-derive from `context_window_size` — rejected (PR #32's reasoning: changes alert semantics for short-context models), though the per-model `match` mechanism lets users approximate it explicitly.

## Risks / Trade-offs

- **[Module-reload tests break if load order changes]** → Keep `CONFIG = Config.load()` at import and assign `MAX_WIDTH`/`SOFT_LIMIT` from it immediately after, preserving the import-time semantics the reload-based tests rely on.
- **[Error row disturbs hand-tuned column math]** → Render it as an ordinary content `border_line` (no elbows/dividers), width-truncated with `_visible_width`; verify across narrow/medium/wide in the demo. Add a `test_config.py` assertion plus a visual check per the skill's post-edit checklist.
- **[3.10 users silently lose toml]** → Documented explicitly in README ("yas.toml requires Python 3.11+; env vars work everywhere"); env layer still fully functional, so no hard breakage.
- **[Alias precedence confusion]** → One resolver, one rule (canonical > alias), covered by an explicit test; aliases documented as deprecated.
- **[CLI/env/toml interaction for `full_width` vs `max_width`]** → `full_width` continues to win over `max_width` in `main()` width math (full width ignores the cap); documented and tested.
- **[Per-model carve-out surprises env users]** → `YAS_SOFT_LIMIT` no longer wins when a per-model entry matches; documented prominently in the README and the `yas.example.toml` comments, and covered by an explicit "per-model toml beats global env" test.
- **[Threading `soft_limit` widens `build_*`/`context_line` signatures]** → New optional/positional `soft_limit: int` parameter on `context_line`/`context_line_compact` and the three builders; default to module `SOFT_LIMIT` so existing direct callers/tests keep working. Verify with the demo across all three layouts.
- **[Substring match too greedy / ambiguous]** → Longest-match + file-order tie-break is deterministic and tested; empty `match` is rejected at load (would match everything) and surfaced in the error row.
- **[Stale `pct_soft` semantics with large `soft_limit`]** → Out of scope here; `risk_zone_color` bands stay absolute token counts (model-independent), matching PR #32's reasoning.

## Migration Plan

1. Merge PR #32 to `main`.
2. Land this change on the `user-config` branch; replace the `YAS_SOFT_LIMIT` one-liner with `Config`-sourced `soft_limit`.
3. No user action required: absent `yas.toml` + unchanged env = identical behaviour. Rollback is reverting the branch; no persisted state or schema migration is involved.

## Open Questions

- None blocking. (Whether `/yas:init` should later offer to copy `yas.example.toml` is deferred; v1 ships the example file + docs only.)
