## Context

The wide layout is built by `build_wide` in `claude/yas/layout.py`. It emits a flat list of `RowSpec`s: a path/model row, a context line, the tokens block, then a sequence of optional **dynamic** sections — plugins, the task checklist, the subagent cohort, and openspec bars — each separated by a dim dotted separator (the first such separator is a heavy "seam" marking the static→dynamic split). `render_layout` walks the rows and dispatches each `kind` to a `Renderer`/`BorderRenderer` method.

Two section renderers are involved:
- `Renderer.task_row(tasks, width, *, compact)` returns a list of content lines: a header (Total Elapsed + glyph + `done/total`) and an active-anchored window of item rows (timer column + `N.` + subject). It derives its inner width from the terminal `width` (`inner_w = width - 3`).
- `Renderer.subagent_row(sub, width, session_inout)` returns one (`\n`-joined) string. Above `width > 100` it produces a two-line form (identity line `▶ type · desc`; continuation line `└ activity … t/m · share · tok↑out · dur · model`); otherwise a one-line collapse. It derives `target_w = width - 4` and self-selects the form from `width`.

Both sections are appended to the row list independently, each preceded by its own separator. When both are present the checklist's right margin is mostly empty while the cohort consumes extra vertical rows.

Border elbows are threaded via `RowSpec.downs`/`ups` (1-indexed visual columns). `border_separator_dim` already supports both `downs` and `ups` (drawing `┬`/`┴`/`┼`); `border_separator` (used for the seam and openspec separators) currently supports only `ups`.

## Goals / Non-Goals

**Goals:**
- Place the task checklist and subagent cohort in two columns within one bordered block in the wide layout when both are present and there is room.
- Redesign the subagent two-line row to be denser (duration-first, `share% · tok · model` cluster, activity-only line 2) and drop the t/m and ↑output fields everywhere.
- Keep all geometry decisions in the layout builder; keep the section renderers pure width-parametric functions.
- Fall back cleanly to today's stacked layout when there isn't room, and leave medium/narrow untouched.

**Non-Goals:**
- No change to medium or narrow layouts beyond the subagent field-set removals that apply to all forms.
- No change to which subagents are visible (`RunningSubagents.visible`) or to the Session Share % denominator (`statusline-info`).
- No combined-height cap beyond what the existing visibility/window logic already produces.
- No new run-state marker glyph to replace `▶`/`✓` — dim/colour carries the distinction.

## Decisions

### D1 — Side-by-side lives entirely in `build_wide`
The composition is a wide-only special case computed inside `build_wide`. Medium/narrow builders are unchanged. *Alternative considered:* a shared helper used by medium too — rejected because medium rarely has the ~92+ columns needed and the added conditional complexity isn't worth it.

### D2 — Two columns: left = tasks (capped), right = subagents (remainder)
`inner = width - 4`; divider is ` │ ` (3 visible cols). `left_w = min(longest_task_line, floor(inner * 0.45))`; `right_w = inner - 3 - left_w`. If `right_w < 40`, abandon and stack. *Alternative:* fixed 50/50 — rejected: wastes space on short task lists and risks a too-narrow cohort column.

### D3 — Render each column independently, then zip
Each column is rendered to a list of lines at its own content width, then combined row-by-row to `max(len(left), len(right))`, padding the shorter column with blank lines of its own width (top-aligned). Each combined row is `f'{left_padded} {divider} {right_padded}'`, emitted as a plain `content` `RowSpec`. *Alternative:* interleave at the builder per agent/task — rejected: couples the two sections' internal layout and breaks the clean per-column renderers.

### D4 — Content-width + form parametrization on the renderers
`task_row` and `subagent_row` gain an explicit content-width parameter; `subagent_row`'s `width > 100` self-decision becomes a builder-supplied form flag (e.g. `twoline: bool`). This lets a ~48-col side-by-side column still use the two-line form. The full-width callers pass the form they'd have selected from terminal width, preserving current behaviour. *Alternative:* dedicated column-variant renderers — rejected: duplicates layout logic.

### D5 — Divider elbows via `border_separator` `downs`
Add a `downs` parameter to `border_separator` mirroring `border_separator_dim`'s `┬`/`┴`/`┼` branch, so the heavy seam above the block can grow a `┬` at the divider column. The separator (or bottom border) below grows a matching `┴`. The divider column is `3 + left_w + 1` (1-indexed visual: content starts at visual col 3, the left column occupies `left_w`, one pad space, then `│`). *Alternative:* don't connect the divider to the separator above — rejected per the grilling decision; the floating top reads as a bug.

### D6 — Subagent two-line redesign (applies to all wide two-line uses)
Line 1: `{dur} {type} · {description}` with right-aligned `· {share%}  {tok} · {model}`. No `▶`/`✓` marker. Done → dim + frozen duration; running → coloured + ticking duration. Line 2: activity-only `└  {glyph} {Tool[arg]}`. Drop the t/m rate and ↑output fields. Line-1 cluster sheds share% → tok; model + duration always retained; description truncates first. The one-line form only loses ↑output, otherwise unchanged.

### D7 — Section ordering and the seam
The side-by-side block occupies the position the checklist currently holds (before the cohort, before openspec). It removes the separator that used to sit between checklist and cohort. The block's top separator carries the existing `pending_ups` seam threading **and** the new divider `downs`; the following separator/border carries the divider `ups`.

## Risks / Trade-offs

- **[Seam can't grow a `┬` today]** → D5 extends `border_separator` with `downs`; covered by a `test_borders.py` case.
- **[Column math off-by-one draws a crooked box]** → divider column derived once and threaded into both bracketing separators; verified by `make demo` across thresholds and an alignment assertion in `test_layout_seam.py`.
- **[Narrow right column makes the two-line cluster illegible]** → the `right_w < 40` fallback to stacked, plus the documented shed order (share% → tok), bound the worst case.
- **[Dropping the run-state marker loses the at-a-glance running/done cue]** → mitigated by retaining dim styling for Done and live colour + ticking timer for running (D6); `subagent-cohort` spec updated accordingly.
- **[Removing t/m and ↑output is a visible contract change]** → reflected in the `subagent-row-layout` spec and `CONTEXT.md` glossary; Session Share % denominator is unchanged.

## Migration Plan

Pure rendering change; no data migration. Ships in one PR. Rollback is reverting the PR — no persisted state or schema is affected. Medium/narrow output is byte-identical except for the universal ↑output/t-m removals in subagent rows.

## Open Questions

None outstanding — the design decisions above were resolved during grilling.
