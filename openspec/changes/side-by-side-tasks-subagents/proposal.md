## Why

In the wide layout the task checklist wastes most of its horizontal room — short task subjects leave a large empty right margin — while the subagent cohort, stacked below it, fights for vertical space. When both sections are present there is enough width to place them side-by-side, using the idle right margin of the checklist for the subagent column and shortening the box. At the same time the subagent two-line row carries low-signal fields (t/m rate, ↑output) that crowd the cluster and can be dropped to make the denser side-by-side column legible.

## What Changes

- **Side-by-side composition (wide only):** when both the task checklist and at least one visible subagent are present and the terminal is wide enough, render the checklist as a left column and the subagent cohort as a right column, separated by a single gradient `│` divider, instead of stacking them as two full-width sections.
- **Content-driven split:** the left (task) column is sized to fit its content up to 45% of the inner width; the subagent column takes the remainder. If the remainder would be narrower than 40 columns, the side-by-side layout is abandoned and the two sections stack full-width exactly as today (graceful fallback).
- **Height reconciliation:** the two columns are rendered independently to their own widths, then zipped top-aligned to the taller column's height, padding the shorter column with blank lines so the divider runs straight from the separator above to the separator below.
- **Divider elbows:** `border_separator` gains `downs` support (mirroring `border_separator_dim`) so the heavy static→dynamic seam can grow a `┬` at the divider column; the separator below grows a matching `┴`.
- **Subagent two-line row redesign (applies in all wide uses, not only side-by-side):** the run-state `▶`/`✓` marker is removed; the elapsed duration moves to the front of line 1; the right cluster becomes `share% · tok · model` (shedding share% → tok under width pressure, always keeping model and duration); line 2 becomes activity-only. The t/m rate and ↑output fields are removed.
- **Subagent one-line row:** the ↑output field is removed; the row is otherwise unchanged.
- **Builder-driven geometry:** `task_row` and `subagent_row` take an explicit content-width, and the subagent two-line/one-line form becomes a builder-supplied flag rather than a `width > 100` self-decision, so a narrow side-by-side column can still use the two-line form.

## Capabilities

### New Capabilities
- `side-by-side-sections`: the wide-layout two-column composition of the task checklist and subagent cohort — the both-present-and-wide-enough trigger, the content-driven column split, the shared gradient divider with border-elbow threading, top-aligned height reconciliation, and the right-column-width fallback to stacked rendering.
- `subagent-row-layout`: the field set and structure of a rendered subagent row — the front-anchored duration, the line-1 `share% · tok · model` cluster and its shed order, the activity-only continuation line, the one-line collapse form, and the removal of the t/m rate and ↑output fields across all forms.

### Modified Capabilities
- `subagent-cohort`: the **Finished-agent visual treatment** requirement no longer distinguishes running from Done via the `▶`/`✓` markers (the duration now occupies that leading position); Done remains dim with a frozen duration, running remains coloured with a live-ticking duration.
- `task-checklist`: the **Layout-specific rendering** requirement is extended so the wide checklist renders into a builder-supplied content width and may appear as the left column of a side-by-side section.

## Impact

- **Code:** `claude/yas/layout.py` (`build_wide` composition, divider/elbow threading, fallback guard), `claude/yas/renderer.py` (`task_row`, `subagent_row`, content-width + form parametrization), `claude/yas/render/borders.py` (`border_separator` `downs` support).
- **Display contract:** the subagent row drops the t/m rate and ↑output; `CONTEXT.md` glossary updated if either term is documented there. Session Share % denominator (`statusline-info`) is unchanged — share% is still computed, only conditionally shed.
- **Tests:** `test/test_borders.py` (`border_separator` downs), `test/test_subagent_rows.py` (new two-line + one-line content), `test/test_layout_seam.py` (side-by-side composition, fallback guard). Visual check via `make demo` across the narrow ↔ medium ↔ wide thresholds.
- **No new dependencies.** Medium and narrow layouts are untouched.
