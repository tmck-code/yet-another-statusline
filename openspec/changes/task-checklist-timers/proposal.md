## Why

Today the statusline shows tasks as a **single** line: a `done/total` count plus the one active task's text (`task_row`, ~L2201). You can't see what's already done, what's coming, or how long the current step has been running. `TaskList.from_session` (~L1042) also accumulates **every** `TaskCreate` in the session into one ever-growing list and throws away per-task transition timestamps — so there is no data for a duration, and the count drifts as stale rounds pile up.

We want the task block to read like a live checklist: every item in the current plan, marked off one-by-one as it completes, each with a timer that starts when work begins on it and freezes at its final duration when done.

## What Changes

- **Per-task timestamps.** `Task` gains `started_at` / `completed_at`. `TaskList.from_session` stamps them from each `TaskUpdate`'s timestamp (latest-run wins; `completed_at` cleared on reopen). A `pending → completed` task that was never `in_progress` has no duration.
- **Plan generation scoping.** A `TaskCreate` that arrives after *all* existing tasks are `completed` starts a new generation; only the latest generation is rendered/counted. A `TaskCreate` while any task is still open appends to the current generation. This keeps `done/total` and the new total-elapsed about *this* plan, not the whole session.
- **Pinned visibility.** `is_visible` stays true while any task is `in_progress`, ignoring `FRESHNESS_CAP` — so a long-running step's live timer is never hidden. The 2-min cap + 20s all-complete grace still apply once nothing is in progress.
- **Full windowed checklist (wide + medium).** `task_row` renders a header (glyph + `done/total` + **Total Elapsed**) followed by an active-anchored window of item rows, capped at **6 content rows including** any `+N done` / `+N more` collapse lines. Each item: state glyph + subject (truncated) + a right-aligned **Task Timer** column. completed = frozen duration; in_progress = live; pending = none.
- **Compact row (narrow).** Narrow — which shows no task info today — gains a single compact line: glyph + `done/total` + the active task's live timer.
- **Pure view helpers** extracted to a new `claude/statusline/tasks_view.py` (importlib-loaded like `themes.py`): `fmt_duration`, `total_elapsed`, `select_window`. This isolates the testable maths from the ANSI/colour composition in `Renderer.task_row` and lets the work parallelise cleanly.

Explicitly **not** included:
- No change to token/cost/context/subagent/openspec rows.
- No new persisted state; the statusline stays a stateless single-pass render. The live timer advances at the harness's existing ~1s refresh cadence (same assumption `rainbow_step` relies on) and freezes during a silent long tool call.

## Capabilities

### New Capabilities
- `task-checklist`: the rendered task checklist contract — plan-generation scoping, per-task timing (live vs frozen), Total Elapsed, the active-anchored 6-row window with collapse affordances, pinned-while-active visibility, and the wide/medium/narrow render variants.

### Modified Capabilities
<!-- None: openspec/specs/ is empty; this is a new capability. -->

## Impact

- `claude/statusline_command.py`:
  - `Task` (~L1025): `+ started_at`, `+ completed_at`.
  - `TaskList.from_session` (~L1042): timestamp capture + generation scoping.
  - `TaskList.is_visible` (~L1118): pinned-while-`in_progress`.
  - `Renderer.task_row` (~L2201): rewritten to return `list[str]` (header + windowed items + collapse lines), with a compact single-line variant.
  - `build_narrow` / `build_medium` / `build_wide` (~L2537 / L2584 / L2643): emit the returned lines as `content` `RowSpec`s.
  - New module-scope glyph constants `GLYPH_TASK_PENDING = '\ue640'`, `GLYPH_TASK_ACTIVE = '\U000f0117'`, `GLYPH_TASK_DONE = '\uf4a7'` (hoisted per the PUA rule); new `importlib` load+bind block for `tasks_view.py`.
- New `claude/statusline/tasks_view.py`: pure `fmt_duration`, `total_elapsed`, `select_window`.
- Tests: parser/visibility/generation in `test/test_task_list.py`; rendering in `test/test_task_row.py`; pure helpers in new `test/test_tasks_view.py`.
- `CONTEXT.md`: glossary entries for **Task Checklist**, **Plan Generation**, **Task Timer**, **Total Elapsed**, **Active Window**.
- **Coordination with `deepen-transcript-reader`** (in flight): that change adds `fold_tasks` in `claude/statusline/transcript.py` and will repoint `TaskList.from_session` to it. Whichever is the live source of the `TaskList` at apply time owns the generation/timestamp logic; the spec describes behaviour, not location. If `fold_tasks` exists, it must carry the same semantics.
