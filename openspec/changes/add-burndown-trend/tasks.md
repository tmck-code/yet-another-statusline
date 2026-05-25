## 1. Pre-edit prep

- [ ] 1.1 Run `uv run pytest -q` and record baseline pass count
- [ ] 1.2 Run `make statusline/test` and confirm the demo animates cleanly at narrow/medium/wide widths
- [ ] 1.3 Run the PUA-glyph audit from the skill on `claude/statusline_command.py` (just the lines we'll touch: `helper`, `model_right_section`, `model_right_section_compact`). Hoist any raw PUA bytes on those lines into module-level constants before any Edit.

## 2. Pure math layer

- [ ] 2.1 Add module-level constants `FIVE_HOUR_MINUTES = 300`, `SEVEN_DAY_MINUTES = 10080`, `FIVE_HOUR_WARMUP_MINUTES = 5`, `SEVEN_DAY_WARMUP_MINUTES = 30` near the other module-level numeric constants
- [ ] 2.2 Add module-level pure helper `burndown_delta(used_pct, resets_at, window_minutes, warmup_minutes, now=None) -> float | None` per the spec, returning `None` for the three suppression cases (no window, expired, in warmup)
- [ ] 2.3 Create `test/test_burndown.py` covering: exact spec example (+10.5), under-pace (-19.5), zero-usage-past-warmup, no-window (`resets_at=0`), expired window, warmup boundary (just-inside and just-outside), 7d window (`window_minutes=10080`)
- [ ] 2.4 `uv run pytest -q test/test_burndown.py` — green

## 3. Renderer presentation layer

- [ ] 3.1 On `Renderer`, add `burndown_trend(self, used_pct, resets_at, window_minutes, warmup_minutes) -> str` that calls `burndown_delta`, picks the arrow/dot glyph, picks the colour bucket (safe/warn/alert at 0.5/5/15 cutoffs, symmetric across direction), formats with one decimal place, and wraps in ANSI + `self.R`. Returns `''` when `burndown_delta` returns `None`.
- [ ] 3.2 If the renderer uses a green palette that doesn't already exist, add the minimum green palette needed (e.g. `self.green`, `self.green_brt`) following the existing palette pattern; otherwise re-use `self.safe`/`self.warn`/`self.alert` directly
- [ ] 3.3 Add tests in `test/test_helper.py` (or a new section if file is already large) covering: each direction × each colour bucket, on-pace dot boundary at `±0.5`, suppressed cases return `''`. Use `strip_ansi` for glyph assertions and check ANSI substring presence for colour assertions.

## 4. Integration — `Renderer.helper()`

- [ ] 4.1 Edit `Renderer.helper()` (~L2399) to insert the burndown trend between `<pct>%` and `T-<delta>`. Position: `<pct>% <trend> T-<delta>`. Trend is suppressed (empty string) → output is byte-identical to today for the suppressed cases.
- [ ] 4.2 Add tests in `test/test_helper.py` for: pre-warmup (no trend in output), mid-window over-burn (trend appears between `%` and `T-`), expired window (existing `∞` behaviour unchanged), 5h window passed to `helper()` uses `FIVE_HOUR_MINUTES` / `FIVE_HOUR_WARMUP_MINUTES`

## 5. Integration — `Renderer.model_right_section()` (wide)

- [ ] 5.1 Edit `model_right_section()` (~L1937) so the 7d block becomes `| <pct>% <trend>` using `SEVEN_DAY_MINUTES` / `SEVEN_DAY_WARMUP_MINUTES`. The 5h portion gets the trend via the helper-call edit in step 4.1, so no further change needed here for 5h.
- [ ] 5.2 Add tests in `test/test_model_section.py` covering: wide layout with both buckets active shows trends for both, 7d-idle (`resets_at=0` or `used_percentage=0`) still suppresses the entire 7d block, 5h-warmup still shows the 5h `%` but no trend
- [ ] 5.3 Verify width accounting via `_visible_width` — the helper returns `(helper_text, right_text, right_w)`; `right_w` is the model pill, unchanged. `helper_text` width changes but is padded into the row by the caller. Confirm with a width-assertion test that includes the trend.

## 6. Integration — `Renderer.model_right_section_compact()` (medium)

- [ ] 6.1 Edit `model_right_section_compact()` (~L1945) so `rate_text` becomes `<pct>% <trend> <h>m`. Use `FIVE_HOUR_MINUTES` / `FIVE_HOUR_WARMUP_MINUTES`. No 7d trend in compact.
- [ ] 6.2 Add tests in `test/test_model_section.py` for the compact path covering: warmup suppression, mid-window over-burn, no-window (no trend)

## 7. Narrow layout — explicit no-op verification

- [ ] 7.1 Locate `model_section_compact()` (~L1843, narrow) and confirm by reading that it does NOT call into trend rendering. No edit needed.
- [ ] 7.2 Add a regression test in `test/test_model_section.py` asserting that the narrow render output contains neither `▲` nor `▼` even when buckets carry mid-window over-burn data.

## 8. CONTEXT.md updates

- [ ] 8.1 Fix the stale line under `### Rate limits` at L92: "Seven-Day Limit ... Currently parsed but not rendered" — replace with the accurate "rendered in the model row as `| <pct>%`" description.
- [ ] 8.2 Add a new term **Burndown Trend** under `### Rate limits` covering: the formula, the ▲/▼/· glyphs and their semantics, suppression conditions (no window, expired window, warmup), and the per-layout rendering policy.
- [ ] 8.3 If a glossary-style canonical-terms list exists in CONTEXT.md, add **Burndown Trend** there too. Check the "Flagged ambiguities" section for any related disambiguation worth recording.

## 9. Demo + visual verification

- [ ] 9.1 Run `make statusline/test` — eyeball: trend renders alongside the 5h and 7d percentages, on-pace dot doesn't flicker, colours match the bucket policy as the demo cycles its sample data.
- [ ] 9.2 Resize the terminal across narrow → medium → wide thresholds during the run; verify trend appears/disappears according to the per-layout policy.
- [ ] 9.3 If a session-info fixture is missing rate-limit data, add a one-frame snapshot test in `test/fixtures/` that exercises `make statusline/test` with mid-window 5h and 7d data so future visual regressions are catchable.

## 10. Final checks

- [ ] 10.1 `uv run pytest -q` — total pass count = baseline (step 1.1) + new tests
- [ ] 10.2 Re-read `claude/statusline_command.py` diff with the PUA audit re-run, confirming no raw PUA bytes were introduced on edited lines
- [ ] 10.3 Skim `claude/mon.py` once and confirm trend renders correctly when a session is in the bright (non-dim) state via `make mon/run` against a real session; log the dim-state behaviour as a known limitation in design.md if needed
- [ ] 10.4 Run `openspec status --change add-burndown-trend` and confirm readiness to archive after merge
