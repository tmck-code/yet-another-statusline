<!--
PARALLELISM & PROGRESS TRACKING

- Mark each subtask `- [x]` IMMEDIATELY upon completion (not in a batch at the
  end) so progress is measurable mid-run.
- Group headers are tagged:
    [SEQ]      must finish before later groups start (serialization point)
    [PARALLEL] independent of sibling [PARALLEL] groups; safe to fan out to
               concurrent subagents AFTER its stated dependency group is done.
- File-conflict rule: groups that edit the SAME region of
  claude/statusline_command.py (Groups 1 and 2) must run sequentially OR in
  isolated git worktrees. Groups 4 (test/test_config.py) and 5 (README,
  CONTEXT.md, yas.example.toml) touch only their own files and are always
  conflict-free. Group 3 edits the builder/render region of
  statusline_command.py — run it after Group 2, or in a worktree alongside.
- Dependency summary:
    0  →  1  →  2  →  {3, 6}
                 1  →  {4, 5}   (4 and 5 need only the final knob names/API from Group 1)
    6 (verification) runs last, after 2, 3, 4, 5.
-->

## 0. Prerequisite [SEQ]

- [x] 0.1 Merge PR #32 (`YAS_SOFT_LIMIT`) to `main`, then rebase/merge `main` into the `user-config` branch so `SOFT_LIMIT` already reads the env var before refactor begins — DONE (merge `99123d9`; `SOFT_LIMIT = int(os.environ.get('YAS_SOFT_LIMIT') or 150_000)` and `test/test_soft_limit_env.py` are on the branch)

## 1. Core Config scaffold [SEQ — single owner; module-scope region of claude/statusline_command.py; blocks Groups 2–5]

- [x] 1.1 Add guarded TOML import near the top imports: `try: import tomllib` / `except ImportError: tomllib = None`
- [x] 1.2 Add a frozen `@dataclass` `Config` with fields `max_width: int`, `full_width: bool`, `soft_limit: int`, `token_window: float`, `theme: str`, `bg_shift: str`, plus `errors: tuple[str, ...]` and `debug_lines: tuple[str, ...]`
- [x] 1.3 Implement an internal per-knob resolver that takes (canonical env name, alias env name(s), toml `(section, key)`, parse/validate callable, default) and walks CLI→`YAS_*`→alias→toml→default, appending a human-readable message to `errors`/`debug_lines` when a *present* value fails validation
- [x] 1.4 Implement the `yas.toml` loader: read `CLAUDE_DIR / 'yas.toml'`; if `tomllib is None` or file missing → empty dict (no error); on parse failure → empty dict + record one `"yas.toml: parse error"` error
- [x] 1.5 Implement `Config.load(env=os.environ, config_dir=CLAUDE_DIR, argv=None)` wiring all six resolver calls with the validation table (max_width int>0; full_width bool/env-truthy; soft_limit int>0; token_window float>0; theme∈THEMES; bg_shift∈{warm,cool})
- [x] 1.6 Add per-model `soft_limit` support: parse the `[[tokens.model]]` array into a validated, order-preserving `soft_limit_models: tuple[(match, limit), …]` field (drop entries with missing/empty `match` or non-int/`<=0` `soft_limit`, recording each as `tokens.model[i]` in `errors`)
- [x] 1.7 Implement `Config.soft_limit_for(model_name)`: lowercase the model id+display_name, keep entries whose `match` is a substring of either, return the longest match's limit (ties → first in file order), else the global `soft_limit`
- [x] 1.8 Create module singleton `CONFIG = Config.load()` at import and assign `MAX_WIDTH`, `SOFT_LIMIT` (= resolved *global*), and the token-rate window constant from it (preserve import-time semantics so module-reload tests keep working)
- [x] 1.9 Emit `CONFIG.debug_lines` to stderr at load time only when `YAS_DEBUG` is set in the environment

## 2. Consuming sites + CLI precedence [SEQ — after Group 1; same file region]

- [x] 2.1 Fold `resolve_theme` into the chain: CLI `--theme` → `YAS_THEME` → `CLAUDE_STATUSLINE_THEME` (alias) → `[appearance].theme` → `statusline-theme` file (lowest-priority legacy fallback) → `CLAUDE_DARK`
- [x] 2.2 Resolve `bg_shift` via Config: CLI `--bg-shift` → `YAS_BG_SHIFT` → `[appearance].bg_shift` → `warm`, keeping CLI at top precedence in `main()`
- [x] 2.3 Source the `full_width` / `max_width` width math in `main()` from Config (full_width continues to win over the max_width cap)
- [x] 2.4 Source `token_window` from Config, honoring `STATUSLINE_TOKEN_WINDOW` as the deprecated alias of `YAS_TOKEN_WINDOW`
- [x] 2.5 Add a `soft_limit: int` parameter to `context_line` / `context_line_compact` (defaulting to module `SOFT_LIMIT`) and thread it from `build_narrow/medium/wide`, which receive the effective value resolved once in `render()` via `CONFIG.soft_limit_for(session.model_name)`

## 3. Visible config-error row [PARALLEL — after Group 2; builder/render region of statusline_command.py]

- [x] 3.1 Add a shared `append_error_row(rows, cfg, width, r)` helper that builds one compact `border_line` content row `⚠ yas.toml: N values ignored (k1, k2, …)`, truncated via `_visible_width` (no elbows/dividers)
- [x] 3.2 Call the helper at the end of `build_narrow`, `build_medium`, and `build_wide` to append the error row above the bottom border, re-threading the bottom-border `ups` — do NOT special-case `render_layout`
- [x] 3.3 Ensure the row is appended only when `CONFIG.errors` is non-empty (no row on clean config) and verify it renders in all three layouts

## 4. Tests [PARALLEL — after Group 1; isolated file test/test_config.py]

- [x] 4.1 Test the precedence chain: env overrides toml; toml overrides default; default when nothing set
- [x] 4.2 Test alias resolution and canonical-wins (`YAS_TOKEN_WINDOW` vs `STATUSLINE_TOKEN_WINDOW`; `YAS_THEME` vs `CLAUDE_STATUSLINE_THEME`)
- [x] 4.3 Test per-knob validation/fallback (bad type, out-of-range, unknown enum) — one bad value falls back while others apply
- [x] 4.4 Test broken TOML → whole file ignored + error recorded; unknown keys/sections ignored
- [x] 4.5 Test the Python-3.10 degrade path by simulating `tomllib = None` (file skipped, env+defaults used, no crash, no error)
- [x] 4.6 Fold PR #32's three `soft_limit` cases (default / `YAS_SOFT_LIMIT=1000000` / empty-string fallback) into this file
- [x] 4.6a Test `soft_limit_for`: longest-match wins (`"opus-4-8[1m]"` over `"opus"` for `claude-opus-4-8[1m]`), match against display_name, fallback to global when nothing matches, file-order tie-break, and per-model toml beating `YAS_SOFT_LIMIT`
- [x] 4.6b Test malformed `[[tokens.model]]` entries (empty/missing `match`, `soft_limit <= 0` or non-int) are dropped, recorded as `tokens.model[i]`, while valid entries still apply
- [x] 4.7 Test error-row presence on rejection, absence on clean config, and narrow-width truncation without breaking the box
- [x] 4.8 Run `uv run pytest -q` — full suite green; pass count = baseline + new tests

## 5. Docs & example file [PARALLEL — after Group 1 fixes final knob names; isolated files]

- [x] 5.1 Add `yas.example.toml` at repo root: sectioned `[layout]`/`[tokens]`/`[appearance]`, every knob commented out at its default, with a one-line comment per knob, plus a commented `[[tokens.model]]` per-model `soft_limit` example (`match = "1m"`)
- [x] 5.2 Update README with the knob matrix (knob / canonical env / legacy alias / toml key / default), the precedence rule, the per-model `soft_limit` override + its "per-model toml beats global env" carve-out, and the "yas.toml needs Python 3.11+; env vars work everywhere" note
- [x] 5.3 Update `CONTEXT.md` with a config section and a glossary entry for the `⚠` config-error row

## 6. Verification [SEQ — last; after Groups 2, 3, 4, 5]

- [x] 6.1 `make statusline/test` — eyeball the animation across narrow↔medium↔wide thresholds; confirm the error row renders correctly (inject a bad `yas.toml` to trigger it) and the box stays aligned
- [x] 6.2 `uv run ruff check` clean on all touched files
- [x] 6.3 Run the PUA-glyph catalogue (skill pre-edit step 2) on every touched line of `statusline_command.py`; hoist any raw PUA glyph to a named constant before final commit
