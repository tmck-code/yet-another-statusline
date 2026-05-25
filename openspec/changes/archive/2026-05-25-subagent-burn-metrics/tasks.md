<!--
PARALLELIZATION GUIDE
- Group 1 (Foundation) is SERIAL and blocks everything else. Do it first, alone.
- After Group 1, Groups 2, 3, and 4 are PARALLEL-SAFE and may be dispatched to
  separate subagents concurrently:
    - Group 2 (math unit tests)   -> needs 1.2, 1.3   -> touches test files only
    - Group 3 (docs / glossary)   -> needs 1.1        -> touches CONTEXT.md only
    - Group 4 (rendering + plumbing) -> needs 1.1-1.3  -> touches statusline_command.py render path
- Group 5 (rendering tests) depends on Group 4. Group 6 (verification) is LAST and depends on all.
- Conflict note: Groups 1 and 4 both edit claude/statusline_command.py. They are
  sequenced (1 before 4), so no concurrent writes to that file. Groups 2/3 do not
  touch it. Only ONE subagent should edit statusline_command.py at a time.

PROGRESS: mark each subtask `- [x]` the MOMENT it is done (not in a batch at the
end) so progress is measurable mid-flight and parallel workers see live state.
-->

## 1. Foundation (SERIAL — do first, blocks Groups 2-4)

- [x] 1.1 Hoist `GLYPH_PIE = '\uf200'  # nf-fa-pie_chart  (subagent session share)` to module scope alongside `ICON_COST` / `GLYPH_MODEL` (~L143). Run the PUA catalogue command from the skill on the lines you touch.
- [x] 1.2 Add module-level pure helper `subagent_avg_tpm(total_input: int, output: int, first_timestamp: float, now: float, floor_seconds: float = 3.0) -> int | None` near `burndown_delta` (~L55): returns `None` when `first_timestamp == 0` or `now - first_timestamp < floor_seconds`, else `round((total_input + output) / ((now - first_timestamp) / 60))`.
- [x] 1.3 Add module-level pure helper `subagent_share(sub_inout: int, session_inout: int) -> float | None`: returns `None` when `session_inout <= 0`, else `sub_inout / session_inout` (0.0–1.0 fraction).

## 2. Math unit tests (PARALLEL-SAFE after Group 1 — test files only)

- [x] 2.1 Test `subagent_avg_tpm`: normal case returns expected t/m for a known duration and token total.
- [x] 2.2 Test `subagent_avg_tpm`: returns `None` when `first_timestamp == 0` and when elapsed `< 3s`.
- [x] 2.3 Test `subagent_share`: normal case returns expected fraction; main + all subagent shares sum to 1.0 for a constructed session.
- [x] 2.4 Test `subagent_share`: returns `None` when `session_inout == 0`.

## 3. Docs / glossary (PARALLEL-SAFE after 1.1 — CONTEXT.md only)

- [x] 3.1 Add `CONTEXT.md` glossary entries for the two new displayed terms: per-subagent **average t/m** (cumulative `(input+output)/min`) and **session share** (`sub_inout / (main_inout + Σ subagent_inout)`), noting the gauge and pie-chart glyphs.

## 4. Rendering + plumbing (after Group 1 — single owner of statusline_command.py)

- [x] 4.1 In `build_wide` (~L2625): compute `session_inout = (usage.billed_in + usage.cache_read) + usage.out + sum(s.total_input + s.output for s in subagents.subagents)` and pass it into each `subagent_row(...)` call.
- [x] 4.2 Thread `session_inout` through `build_medium` (~L2590) and `build_narrow` (~L2519) `subagent_row` calls as a pass-through argument (these layouts must NOT render the cluster).
- [x] 4.3 In `Renderer.subagent_row` (~L2064): add the `session_inout: int` parameter; in the `width > 100` branch only, compute `tpm = subagent_avg_tpm(...)` and `share = subagent_share(sub.total_input + sub.output, session_inout)`, build the cluster `· {ICON_TOK_RATE} {tpm} t/m · {GLYPH_PIE} {pct}%` with t/m in `self.TOK` (flat) and the share percentage coloured via the fill gradient on `share`; omit each figure when its helper returns `None`.
- [x] 4.4 Implement atomic pad-based drop in the line-2 assembly: build `right2` with the cluster appended; if including it makes `pad2` fall below the minimum gap (2 cols, via `_visible_width`), drop the WHOLE cluster and fall back to `⧗tok · $cost`. Never render only one of the two figures.

## 5. Rendering tests (after Group 4)

- [x] 5.1 Test the wide row (>100 cols, ample width) includes both `t/m` and `%` figures (assert via `strip_ansi`).
- [x] 5.2 Test the atomic drop at the width boundary: just below the threshold renders neither figure; just above renders both — never exactly one.
- [x] 5.3 Test the narrow row (≤100 cols) renders neither figure and is otherwise unchanged.

## 6. Verification (LAST — after all groups)

- [x] 6.1 `uv run pytest -q` is green; pass count = baseline + new tests.
- [x] 6.2 `make statusline/test` — eyeball the cluster across the narrow→medium→wide thresholds; confirm elbows/borders still align and the share colour scales with magnitude.
- [x] 6.3 Render one static frame for a wide width and confirm cluster placement: `COLUMNS=160 uv run python claude/statusline_command.py < claude/statusline/session-info-example.json`.
