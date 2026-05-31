## 1. Setup & baseline (serial)

- [x] 1.1 Record baseline: run `uv run pytest -q` and note the pass count; run `make statusline/test` and confirm the demo renders cleanly across narrow/medium/wide.
- [x] 1.2 Add `[tool.pytest.ini_options]` with `pythonpath = ["claude"]` to `pyproject.toml` so `import statusline.<module>` and `import statusline_command` resolve under pytest. Run `uv run pytest -q` — still green (no new modules yet).
- [x] 1.3 Snapshot the monolith for read-only copy-out: `git show HEAD:claude/statusline_command.py` (or keep the working copy untouched) as the source of truth all Wave A–G jobs copy bands from. Establish the rule: **Wave A–G jobs create only new files under `claude/statusline/` and repoint their own test files; none edits `statusline_command.py`.**

## 2. Wave A — constants (serial, gates everything)

- [x] 2.1 Create `claude/statusline/constants.py` by copying verbatim: ANSI colour constants (`CLR_*`, `RESET`, `BOLD`, `ITALIC`), the escape-encoded glyph constants (`GLYPH_*`, `ICON_*`, `SPARK_*`, `PILL_*`), `BarChars`, width constants (`MIN_WIDTH`, `NARROW_WIDTH`, `MEDIUM_WIDTH`, `DEFAULT_MAX_WIDTH`, `DEFAULT_SOFT_LIMIT`, `DEFAULT_TOKEN_WINDOW`, `DEFAULT_THEME`), rate-limit window constants, `RAINBOW_PALETTE`, `BG_LUM_THRESHOLD`, `LIVE_DIM`, `_ANSI_RE`, `HOME`, `CLAUDE_DIR`. Copy glyph lines as the existing `\uXXXX` escapes — never transcribe raw PUA characters.
- [x] 2.2 PUA integrity check: grep `constants.py` for raw PUA codepoints (U+E000–F8FF, U+F0000–FFFFD) — expect zero raw hits; confirm the glyph-constant count matches the monolith's.
- [x] 2.3 Repoint pure-constant tests to `import statusline.constants as constants` (the constants-only assertions in `test_pure_helpers` for `RAINBOW_PALETTE`, the `SPARK_*` set used by `test_sparkline`). Run those test files green.

## 3. Wave B — text / session / metrics / config (parallel; each creates only new files)

- [x] 3.1 `[parallel]` Create `claude/statusline/text.py`: `_is_wide`, `_visible_width`, `_middle_ellipsis`, `fmt_tok`, `fmt_dur`, `sparkline_width`, `terminal_width` (import width consts + `_ANSI_RE` from `constants`). Repoint `test_pure_helpers` (the `_visible_width`/`_middle_ellipsis`/`fmt_tok`/`sparkline_width` cases).
- [x] 3.2 `[parallel]` Create `claude/statusline/session.py`: `_as_int/_as_float/_as_str`, `_parse_iso_to_epoch`, and `Model`, `OutputStyle`, `Effort`, `Thinking`, `CurrentUsage`, `RateBucket`, `Workspace`, `Cost`, `ContextWindow`, `RateLimits`, `SessionInfo` (+ their `from_dict`). Repoint `test_session_info_pure`, `test_from_dict_parsers`, `test_workspace_plugins`.
- [x] 3.3 `[parallel]` Create `claude/statusline/metrics.py`: `burndown_delta`, `subagent_avg_tpm`, `subagent_share`. Repoint `test_burndown`, `test_subagent_metrics`.
- [x] 3.4 `[parallel]` Create `claude/statusline/config.py`: `_parse_pos_int/_parse_pos_float/_parse_bool/_parse_theme/_parse_bg_shift`, `_env_sources`, `_resolve`, `_legacy_theme_sources`, `_parse_argv`, `_load_toml`, `_parse_models`, `Config` (with `.load`, `.soft_limit_for`). Import `DEFAULT_*` from `constants`. **Do not** create a module-level `CONFIG`/`SOFT_LIMIT`/`MAX_WIDTH` singleton. Repoint `test_config`, `test_soft_limit_env`.
- [x] 3.5 Run `uv run pytest -q` — full suite green (un-repointed tests still hit the intact monolith).

## 4. Wave C — tokens + filesystem/transcript readers (parallel fan-out)

- [x] 4.1 `[parallel]` Create `claude/statusline/tokens.py`: `TokenAccounting`, `compute_session_cost`, `compute_day_cost`, `TokenLog`, `TokenRate` (import `Model`/usage types from `session`, `CLAUDE_DIR` from `constants`). Repoint `test_token_log`, `test_token_rate`, `test_model_cost_rates`, `test_session_cost_math`.
- [x] 4.2 `[parallel]` Create `claude/statusline/git.py`: `GitInfo`. Repoint `test_git_info`.
- [x] 4.3 `[parallel]` Create `claude/statusline/skills.py`: `LoadedSkills`. Repoint `test_loaded_skills`.
- [x] 4.4 `[parallel]` Create `claude/statusline/subagents.py`: `RunningSubagent`, `RunningSubagents`. Repoint `test_running_subagents`.
- [x] 4.5 `[parallel]` Create `claude/statusline/tasks.py`: `Task`, `TaskList`. Repoint `test_task_list`.
- [x] 4.6 `[parallel]` Create `claude/statusline/transcript.py`: `TranscriptUsage`. Repoint `test_transcript_usage`, `test_transcript_usage_props`.
- [x] 4.7 `[parallel]` Create `claude/statusline/openspec.py`: `OpenSpec`. Repoint `test_openspec`.
- [x] 4.8 Run `uv run pytest -q` — full suite green.

## 5. Wave D — pill / gradient (parallel)

- [x] 5.1 `[parallel]` Create `claude/statusline/gradient.py`: `GradientEngine`, `rainbow_step/rainbow_at/rainbow_color`, `model_key`, `_scale`, `paint_bg_span`, `pill_gradient_fg` (import glyphs/palette from `constants`, `_visible_width` from `text`). Repoint `test_gradient_math` and the `Renderer`-free cases of `test_sparkline`.
- [x] 5.2 `[parallel]` Create `claude/statusline/pill.py`: `Pill` + its `border_char`/`border_fg`/`gradient_fg` helpers (import `PILL_*` from `constants`, gradient fg from `gradient` if needed — confirm direction keeps the DAG acyclic; if `Pill` needs `pill_gradient_fg`, that function moves to `gradient` and `pill` imports it).
- [x] 5.3 Run `uv run pytest -q` — full suite green.

## 6. Wave E — borders (serial)

- [x] 6.1 Create `claude/statusline/borders.py`: `BorderRenderer` (imports `gradient`, `pill`, `constants`, `text`). Repoint `test_borders`.
- [x] 6.2 Run `uv run pytest -q` — green.

## 7. Wave F — renderer (serial)

- [x] 7.1 Create `claude/statusline/renderer.py`: `Renderer` and all section helpers (`path_git`, `path_git_compact`, `model_section*`, `path_model_row`, `plugins_skills`, `tokens_cost`, `context_line*`, `openspec_bar`, `helper`, colour pickers including the risk-zone colour). Imports `borders`, `gradient`, `constants`, `text`, `session`, `tokens`, and the reader modules as needed.
- [x] 7.2 Repoint single-module Renderer tests: `test_model_section`, `test_context_line`, `test_tokens_cost`, `test_renderer_colour_pickers`, `test_helper`, `test_path_git`, `test_plugins_skills`, `test_openspec_bar`, `test_risk_zone_color`, `test_bar_builders`.
- [x] 7.3 Run `uv run pytest -q` — green; run `make statusline/test` and eyeball elbow/pill alignment.

## 8. Wave G — layout + integration tests (serial)

- [x] 8.1 Create `claude/statusline/layout.py`: `RowSpec`, `LayoutSpec`, `append_error_row`, `build_narrow`, `build_medium`, `build_wide`, `render_layout` (import `renderer`, `session`, reader modules, `config` for `soft_limit`). `build_*` keep their explicit `soft_limit` parameter.
- [x] 8.2 Repoint layout + cross-module integration tests (these pull `Renderer` + `build_*` + data classes together, so they import several `statusline.*` modules module-qualified): `test_layout_seam`, `test_layout_subagent_rows`, `test_subagent_rows`, `test_task_row`, `test_themes`. Replace `sl.MAX_WIDTH`/`sl.SOFT_LIMIT` references with explicit literals or `config.DEFAULT_*`.
- [x] 8.3 Run `uv run pytest -q` — green; `make statusline/test` — alignment intact.

## 9. Wave H — collapse to thin entrypoint (serial)

- [x] 9.1 Create `claude/statusline/app.py`: `render` (resolving `Config.load()` live, threading `soft_limit` into `build_*`), `resolve_theme`, `main`. Import `themes` via `from statusline.themes import Theme, ModelColors, THEMES, CLAUDE_DARK`. Repoint `test_render_callable` to `statusline.app`.
- [x] 9.2 Rewrite `claude/statusline_command.py` to the thin entrypoint (`from statusline.app import main` + `if __name__ == '__main__': main()`); delete all extracted bands from it.
- [x] 9.3 Remove the import-time globals (`CONFIG`, `SOFT_LIMIT`, `MAX_WIDTH`) entirely; confirm nothing references them.
- [x] 9.4 Simplify `test/conftest.py`: remove the `spec_from_file_location` shim (pytest `pythonpath` now resolves `statusline.*`); keep `strip_ansi`/`_visible_width` helpers and the hooks header.
- [x] 9.5 Repoint `claude/mon.py`: `from statusline.app import render, resolve_theme` and `from statusline.constants import MIN_WIDTH`; drop its manual `sys.path.insert`. Confirm `test_mon_*` still pass.
- [x] 9.6 Repoint `test_themes` (and any remaining tests) to `from statusline.themes import ...` where they read `THEMES`/`CLAUDE_DARK`/`Theme`.

## 10. Verification & docs (serial)

- [x] 10.1 Orphan check: assert `statusline_command.py` defines no symbol that also lives in a `statusline` package module (no leftover duplicated bands).
- [x] 10.2 Cycle check: import every `statusline` module in isolation — no circular-import error; confirm the readers reference no render-layer symbol.
- [x] 10.3 Final `uv run pytest -q` — pass count ≥ baseline; `make statusline/test` — narrow/medium/wide all align.
- [x] 10.4 Runtime smoke: `COLUMNS=160 uv run python claude/statusline_command.py < claude/statusline/session-info-example.json` renders a box identical to pre-split.
- [x] 10.5 Add a "Module map" section to `CONTEXT.md` mapping each module to its canonical concept; add `mypy`/`ruff` pass over `claude/statusline/`.
