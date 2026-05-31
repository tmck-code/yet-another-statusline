<!--
Parallelization legend (see design.md → Parallel Execution):

  §2 Foundation [F]  — SERIAL, must land first. Owns ALL top-of-file edits to
                       statusline_command.py (glyph constants, Task fields,
                       tasks_view importlib bind) + the shared contract.
  §3 Parser   [A] ┐
  §4 Helpers  [B] ├─ PARALLEL after F. Disjoint file/region ownership; one test
  §5 Renderer [C] │   file each; no two edit the same region.
  §6 Layout   [D] ┘
  §7 Docs     [G]  — PARALLEL after F (CONTEXT.md only).
  §8 Verify   [V]  — SERIAL, last. Integrates A→C→D, runs the full gate.

Ownership (no other unit edits these):
  [A] statusline_command.py: TaskList class region   + test/test_task_list.py
  [B] claude/statusline/tasks_view.py (bodies)        + test/test_tasks_view.py (new)
  [C] statusline_command.py: Renderer.task_row region + test/test_task_row.py
  [D] statusline_command.py: build_narrow/medium/wide + test/test_layout_*.py
  [G] CONTEXT.md
-->

## 1. Baseline (serial, before anything)

- [x] 1.1 Run `uv run pytest -q` and record the pass count as the green baseline
- [x] 1.2 Run `make statusline/test` and eyeball the demo across narrow→medium→wide as the visual baseline

## 2. Foundation [F] — serial, lands the contract first

- [x] 2.1 Hoist state-glyph constants at module scope (per the PUA rule), alongside `GLYPH_TASKS`: `GLYPH_TASK_PENDING = '\ue640'`, `GLYPH_TASK_ACTIVE = '\U000f0117'`, `GLYPH_TASK_DONE = '\uf4a7'`, each with a `# nf-…` comment
- [x] 2.2 Add `started_at: float | None = None` and `completed_at: float | None = None` to the `Task` dataclass (~L1025); defaults preserve back-compat
- [x] 2.3 Create `claude/statusline/tasks_view.py` with **signatures + docstrings + placeholder bodies** for: `fmt_duration(secs: float) -> str`, `total_elapsed(tasks, now: float) -> float | None`, `select_window(tasks, budget: int = 6) -> WindowSlice`, and a `WindowSlice` dataclass (`items: list[Task]`, `done_hidden: int`, `more_hidden: int`). No ANSI, no I/O
- [x] 2.4 Add the `importlib` load+bind block for `tasks_view.py` in `statusline_command.py`, mirroring the `themes.py` loader (~L19-26); bind `fmt_duration`, `total_elapsed`, `select_window`, `WindowSlice`
- [x] 2.5 Change the `Renderer.task_row` signature to `task_row(self, tasks: TaskList, width: int, *, compact: bool = False) -> list[str]` returning the current single line wrapped in a one-element list; update the two call sites in `build_medium`/`build_wide` to iterate (`for line in r.task_row(...): rows.append(RowSpec('content', content=line))`)
- [x] 2.6 Run `uv run pytest -q` — still green (placeholders + list-wrapping preserve behaviour); adjust only the directly-affected task_row assertion if it asserted a `str`

## 3. Parser [A] — parallel — TaskList only

- [x] 3.1 In `test_task_list.py`, add timing tests: `TaskUpdate→in_progress` sets `started_at` and clears `completed_at`; `→completed` sets `completed_at`; reopen overwrites `started_at` + clears `completed_at`; `pending→completed` leaves `started_at` `None`
- [x] 3.2 Implement timestamp capture in the live `TaskList` source (`from_session`, or `fold_tasks` if `deepen-transcript-reader` has already repointed it) per D1
- [x] 3.3 Add generation-scoping tests: `TaskCreate` while all-completed starts a fresh generation (ids restart at 1, prior dropped); `TaskCreate` while any task open appends; `total`/`completed` count only the latest generation
- [x] 3.4 Implement generation scoping per D2
- [x] 3.5 Add visibility tests: `in_progress` keeps `is_visible()` true past `FRESHNESS_CAP`; with nothing in progress the 120s cap + 20s all-complete grace still apply
- [x] 3.6 Implement pinned visibility in `is_visible` per D5
- [x] 3.7 `uv run pytest -q test/test_task_list.py` green

## 4. View helpers [B] — parallel — pure, new module + new test file

- [x] 4.1 In new `test_tasks_view.py`, add `fmt_duration` tests: `0:07`, `12:04`, zero-padded seconds, rollover to `h:mm:ss` at ≥3600s, `0:00` at 0
- [x] 4.2 Implement `fmt_duration` per D4
- [x] 4.3 Add `total_elapsed` tests: live span (earliest `started_at`→`now`) while any in_progress; frozen span (→latest `completed_at`) otherwise; `None` when nothing ever started
- [x] 4.4 Implement `total_elapsed` per D6
- [x] 4.5 Add `select_window` tests: short plan returns all items, no collapse; long plan keeps the `in_progress` item and **total rows (items + `+N done`/`+N more`) ≤ budget** across active positions; no-active → first pendings; all-complete → last completeds; `done_hidden`/`more_hidden` counts correct
- [x] 4.6 Implement `select_window` per D3
- [x] 4.7 `uv run pytest -q test/test_tasks_view.py` green

## 5. Renderer [C] — parallel — Renderer.task_row only

- [x] 5.1 In `test_task_row.py`, build `TaskList`/`Task` fixtures **directly** (not via `from_session`) and assert (via `strip_ansi`/`_visible_width`): full-list header line shows glyph + `done/total` + Total Elapsed; each item shows the correct state glyph; completed shows frozen duration, in_progress shows live, pending shows none; timers right-align; subjects truncate with `…` before the timer column; `+N done`/`+N more` lines appear when `select_window` reports hidden counts
- [x] 5.2 Implement the full-list branch of `task_row` (wide/medium) using `select_window`, `total_elapsed`, `fmt_duration`, and the §2.1 glyph constants; dim completed timers, bright the live one (D4/D7/D8/D10)
- [x] 5.3 Add narrow-compact tests: single line of glyph + `done/total` + active live timer; timer omitted when nothing in_progress; no subject
- [x] 5.4 Implement the `compact=True` branch returning a one-element list per D7
- [x] 5.5 `uv run pytest -q test/test_task_row.py` green

## 6. Layout wiring [D] — parallel — build_* only

- [x] 6.1 Add/extend `test_layout_*` coverage: `build_wide` and `build_medium` emit one `content` `RowSpec` per line returned by `task_row` (header + items + collapse), gated on `tasks.is_visible()`; `build_narrow` emits the single compact line when visible (it renders no tasks today). Tests may stub `task_row` to a fixed `list[str]`
- [x] 6.2 Update `build_wide` (~L2643) and `build_medium` (~L2584) to iterate `task_row(tasks, width)` lines into `content` rows, preserving the seam/`sep_kind` threading already around the task block
- [x] 6.3 Add the compact task line to `build_narrow` (~L2537): when `tasks.is_visible()`, append `RowSpec('content', content=...)` from `task_row(tasks, width, compact=True)` and the surrounding `separator_dim`, matching the subagent-row pattern
- [x] 6.4 `uv run pytest -q test/test_layout_*.py` green

## 7. Docs [G] — parallel after F — CONTEXT.md only

- [x] 7.1 Add glossary entries to `CONTEXT.md`: **Task Checklist**, **Plan Generation**, **Task Timer** (live vs frozen), **Total Elapsed**, **Active Window** — names matching the implemented identifiers

## 8. Verify [V] — serial, last

- [x] 8.1 Integrate the A→C→D edits to `statusline_command.py` (disjoint regions; resolve any line-number-only overlaps)
- [x] 8.2 `uv run pytest -q` green — pass count ≥ baseline plus the new tests (§3–§6)
- [x] 8.3 `make statusline/test` — eyeball the checklist across narrow→medium→wide: counts, glyphs per state, live vs frozen timers, right-aligned timer column, `+N` collapse lines, and that the box stays ≤6 task content rows on a long plan
- [x] 8.4 If `deepen-transcript-reader` is also in flight, confirm `fold_tasks` and `TaskList.from_session` carry identical generation/timestamp semantics (no drift)
- [x] 8.5 Confirm `CONTEXT.md` glossary terms match the implemented names
- [x] 8.6 `npx @fission-ai/openspec validate task-checklist-timers` passes
