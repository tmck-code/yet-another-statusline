<!--
EXECUTION PROTOCOL — read before starting.

Progress observability (MANDATORY):
- Any agent — the main/orchestrating agent OR any subagent — MUST mark a subtask
  `- [x]` IMMEDIATELY upon completing it, by editing this file in place. Do not
  batch checkbox updates to the end of a group or the end of a session. The
  checkbox state in this file is the single source of truth for spec progress;
  stale checkboxes make the run un-observable.
- A subtask is "done" only when its stated verification passes (tests green /
  demo eyeballed / file present). Mark it the moment that holds, not before.

Fanout plan (groups are tagged [PARALLEL] or [SEQUENTIAL]):
- Group 1 (shared baseline) runs first, by the orchestrator, alone.
- Groups 2, 3, 4 are INDEPENDENT and SHOULD fan out to three parallel workers.
  Group 2 edits borders.py only. Groups 3 and 4 both edit renderer.py but
  DIFFERENT methods (`subagent_row` vs `task_row`) plus their own call sites in
  layout.py; run them in ISOLATED WORKTREES and let the orchestrator merge, or
  serialize 3→4 if sharing one tree.
- Group 5 is SEQUENTIAL: it depends on 2, 3 and 4 all being merged.
- Group 6 is SEQUENTIAL: it depends on 5.
Each worker marks its own subtasks done as it goes.

Design references: D1–D7 and specs side-by-side-sections / subagent-row-layout /
subagent-cohort / task-checklist.
-->

## 1. Shared baseline [SEQUENTIAL — orchestrator, do first]

- [ ] 1.1 Read `CONTEXT.md` and note the canonical terms touched (subagent row fields, t/m rate, output); confirm whether "t/m"/"↑output" appear in the glossary
- [ ] 1.2 Run the PUA glyph catalogue over `claude/yas/renderer.py`, `claude/yas/render/borders.py`, `claude/yas/layout.py`; record which touched lines carry PUA glyphs (hoist to `constants.py` before any Edit that hits them)
- [ ] 1.3 Baseline `make test` and record the pass count; baseline `make demo` and eyeball the current stacked tasks+subagents at wide width

## 2. Border separator downs support [PARALLEL — Worker A; file: render/borders.py]

- [ ] 2.1 Add a `downs: tuple[int, ...]` parameter to `BorderRenderer.border_separator`, drawing `┬` at down columns, `┴` at up columns, and `┼` where both coincide (mirror the branch in `border_separator_dim`)
- [ ] 2.2 Update the `Renderer.border_separator` delegator and the `separator`/`separator_seam` branches in `render_layout` to pass `downs` through
- [ ] 2.3 Add `test/test_borders.py` cases: `border_separator` draws `┬` at a down column, `┴` at an up column, and `┼` where they coincide; assert positions via `_visible_width`
- [ ] 2.4 `make test` green for the borders module

## 3. Subagent row redesign [PARALLEL — Worker B; isolated worktree; files: renderer.py `subagent_row`, layout.py call sites, constants.py if PUA]

- [ ] 3.1 Add an explicit content-width parameter and a `twoline: bool` form flag to `Renderer.subagent_row`; remove the internal `width > 100` self-decision (D4)
- [ ] 3.2 Two-line form (D6): move elapsed duration to the front of line 1; drop the `▶`/`✓` marker; render line 1 as `{dur} {type} · {description}`
- [ ] 3.3 Two-line line-1 right cluster: `· {share%}  {tok} · {model}`; REMOVE the t/m rate and ↑output fields entirely
- [ ] 3.4 Two-line line 2: activity-only `└  {glyph} {Tool[arg]}`, no right-aligned metrics
- [ ] 3.5 Done vs running treatment (subagent-cohort delta): Done → dim colours + frozen duration; running → live colours + ticking duration; no marker glyph either way
- [ ] 3.6 Line-1 cluster shedding (D6 / subagent-row-layout): truncate description first, then shed share% → tok; always keep model and the front duration
- [ ] 3.7 One-line collapse form: remove the ↑output field only; leave marker/type/model/verb/token/duration otherwise unchanged
- [ ] 3.8 Update `subagent_row` call sites in `build_narrow`/`build_medium`/`build_wide` to pass the content-width and the form flag the builder would have chosen from terminal width (preserve current full-width behaviour)
- [ ] 3.9 Update/add `test/test_subagent_rows.py`: two-line duration-first + `share%·tok·model` cluster, absence of t/m and ↑output, line-2 activity-only, shed order, done-dim/frozen vs running-live, one-line drops ↑output; widths via `_visible_width`
- [ ] 3.10 `make test` green for the subagent row tests

## 4. Task row content-width [PARALLEL — Worker C; isolated worktree; files: renderer.py `task_row`, layout.py call sites]

- [ ] 4.1 Add an explicit content-width parameter to `Renderer.task_row`; render header + Active Window into the supplied width instead of deriving from terminal `width` (`inner_w`) (D4 / task-checklist delta)
- [ ] 4.2 Confirm subject truncation and the trailing timer-column alignment still hold at narrow supplied widths (the future left-column width)
- [ ] 4.3 Update `task_row` call sites in `build_narrow`/`build_medium`/`build_wide` to pass the content-width (preserve current full-width behaviour)
- [ ] 4.4 Update/add `test/test_task_checklist`-area tests: `task_row` honours a supplied narrow width, subjects truncate to fit, timers right-align; widths via `_visible_width`
- [ ] 4.5 `make test` green for the task row tests

## 5. Side-by-side composition in build_wide [SEQUENTIAL — after 2, 3, 4 merged; file: layout.py]

- [ ] 5.1 Add a helper that, given the rendered left (task) and right (subagent) line lists and their column widths, zips them top-aligned to the taller height, padding the shorter with blank lines of its own width, and joins each row as `{left_pad} {divider} {right_pad}` (D3 / height-reconciliation requirement)
- [ ] 5.2 Compute the split in `build_wide`: `inner = width - 4`; `left_w = min(longest_task_line, floor(inner*0.45))`; `right_w = inner - 3 - left_w`; divider ` │ ` at `divider_col = 3 + left_w + 1` (D2)
- [ ] 5.3 Gate the composition: only when the wide layout has BOTH a visible checklist AND ≥1 visible subagent; if `right_w < 40`, fall back to today's stacked sections (side-by-side-sections trigger + fallback)
- [ ] 5.4 Render the left column via `task_row(content_width=left_w)` and the right column via `subagent_row(content_width=right_w, twoline=True)` for each visible subagent; build the combined `content` RowSpecs
- [ ] 5.5 Thread divider elbows: the separator above the block gets `downs=(divider_col,)` alongside the existing `pending_ups` seam threading; the separator/border below gets `ups=(divider_col,)` (D5/D7); remove the now-defunct separator that sat between checklist and cohort
- [ ] 5.6 Preserve the unchanged stacked path for the one-section and below-threshold cases; verify medium/narrow builders are untouched

## 6. Integration, docs, and visual check [SEQUENTIAL — after 5]

- [ ] 6.1 Add `test/test_layout_seam.py` cases: inject a `SessionView` with both a checklist and a subagent cohort at a wide width → assert a side-by-side block with a continuous divider column (matching `┬`/`│`/`┴`); and at a width that forces `right_w < 40` → assert stacked fallback
- [ ] 6.2 Add a layout test asserting the single-section cases (tasks-only, subagents-only) still render full-width and stacked
- [ ] 6.3 Update `CONTEXT.md` if "t/m" / "↑output" are documented — record their removal from the subagent row; confirm Session Share % denominator wording is unchanged
- [ ] 6.4 Full `make test` green at or above the baseline pass count plus the added tests
- [ ] 6.5 `make demo` across narrow ↔ medium ↔ wide: confirm every `┬` lines up with the divider `│` and a `┴`; the box closes straight; the side-by-side block appears only when both sections are present and wide enough
- [ ] 6.6 `openspec validate "side-by-side-tasks-subagents"` passes
