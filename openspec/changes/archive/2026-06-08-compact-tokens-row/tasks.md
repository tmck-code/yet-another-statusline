## 1. Config knob: show_day_stats

- [x] 1.1 Add `show_day_stats: bool = True` field to the `Config` frozen dataclass in `claude/yas/config.py`.
- [x] 1.2 Resolve it through the existing precedence chain: canonical `YAS_SHOW_DAY_STATS` env, `[tokens].show_day_stats` toml, default `True`. Add a boolean validator where env form treats `0`/`false`/`no` (case-insensitive) as false and any other non-empty value as true; an invalid toml value falls back to default and is recorded as a config error.
- [x] 1.3 Add a default constant to `constants.py` if the other defaults live there (mirror `token_window`/`DEFAULT_*`).
- [x] 1.4 Update `test_config.py`: env `0` → false, toml `false` → false, default true, non-boolean toml rejected to default + error recorded, `YAS_SHOW_DAY_STATS` beats toml.

## 2. Single-row block-element sparkline

- [x] 2.1 Add `GradientEngine.sparkline_1row(history, live=False) -> str` in `claude/yas/render/gradient.py`: map each value to `round(ratio*8)` over `[0,8]`, index ` ▁▂▃▄▅▆▇█`, colour by ratio via `spark_color`, dim the last cell when `live`.
- [x] 2.2 Add the ` ▁▂▃▄▅▆▇█` block string as a named constant (reuse/extend `GradientEngine.SPARK_CHARS = '▁▂▃▄▅▆▇█'` — note it already exists; add the leading blank handling in the method).
- [x] 2.3 Remove the two-row `sparkline` and the `_spark_rise`/`_spark_fall`/`_spark_flat` helpers from `GradientEngine` once no caller remains.
- [x] 2.4 Remove the now-unused `SPARK_RISE_*` / `SPARK_FALL_*` constants from `constants.py` (grep first: `SPARK_RISE`, `SPARK_FALL`, `_spark_rise`, `_spark_fall`, `_spark_flat`).
- [x] 2.5 Update `test_gradient_math.py`: assert glyphs come only from ` ▁▂▃▄▅▆▇█`, none from U+1FBxx; cover empty history, flat history, and a rising/falling series.

## 3. Collapse tokens_cost to one line

- [x] 3.1 Rewrite `Renderer.tokens_cost` (`claude/yas/renderer.py`) to build ONE content line: tokens column, gradient `│`, cost column, gradient `│`, rate label + `sparkline_1row`. Keep the return shape `([single_line], (col1, col2), mark_col)`.
- [x] 3.2 With day stats on, format the tokens column as `↓ <sess_in>/<day_in> (<sess_cache>/<day_cache>) ↑ <sess_out>/<day_out>` and the cost column as `$<sess_cost> / $<day_cost>`, using `fmt_tok` (keep `M`/`K` suffixes in the cache parenthetical) and `_visible_width` for column geometry (drop the fixed `IN_W/CACHE_W/OUT_W` right-justify for the merged form).
- [x] 3.3 Add the `show_day_stats=False` branch: session-only `↓ <sess_in> (<sess_cache>) ↑ <sess_out>`, cost `$<sess_cost>`, rate+spark unchanged; same three-column structure.
- [x] 3.4 Thread `show_day_stats` into `tokens_cost` (add a parameter; `build_wide` passes it from `view.cfg`).
- [x] 3.5 Fetch sparkline history over `TokenRate.WINDOW` (60s) instead of `TokenRate.WINDOW * 2`. Remove the `spark_mark_col` tick marker (D4): return `mark_col = 0` and stop computing the midpoint.

## 4. Layout threading

- [x] 4.1 Update `build_wide` in `claude/yas/layout.py` to pass `show_day_stats` into `tokens_cost` and handle the single-element `line_tokens` (the loop already iterates; confirm the separators/seam and `vsep_cols`/`spark_mark_col` elbow threading are correct for one row).
- [x] 4.2 Verify the `┬`/`┴` elbows on the separators above and below the row align with every `│` in the single line (`vsep_cols`); confirm no spark-mark elbow is threaded now that the tick marker is removed.
- [x] 4.3 Update `test_layout_seam.py` and `test_tokens_cost.py`: assert one content line is returned, the merged `session/day` content, the session-only variant under `show_day_stats=False`, and that divider columns match the rendered `│` positions.

## 5. Verify & document

- [x] 5.1 Run the PUA-glyph catalogue over touched files; hoist any raw PUA glyph on an edited line to a `constants.py` constant before editing.
- [x] 5.2 `make test` green (baseline pass count + new tests).
- [x] 5.3 `make demo` across narrow→medium→wide thresholds: tokens row is one line, elbows aligned, sparkline reads as block elements, day-stats toggle behaves.
- [x] 5.4 Update `CONTEXT.md` glossary if any displayed term changed (e.g. the merged `session/day` figures, the new sparkline).
- [x] 5.5 Delete `ops/proto_compact_tokens_row.py` and `ops/NOTES.proto_compact_tokens_row.md`.
