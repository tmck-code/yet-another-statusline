## Context

The statusline is a stateless single-pass terminal painter (`claude/statusline_command.py`), layered `GradientEngine` → `BorderRenderer` → `Renderer`, with layouts assembled by `build_narrow` / `build_medium` / `build_wide` into a `LayoutSpec` of `RowSpec`s and walked by `render_layout`. Tasks today:

- `Task` (~L1025): `id`, `subject`, `active_form`, `status` (`pending`/`in_progress`/`completed`).
- `TaskList.from_session` (~L1042): walks the session jsonl, folds `TaskCreate`/`TaskUpdate` `tool_use` items by id, keeps only `last_event_ts`. Accumulates **all** session tasks.
- `TaskList.is_visible` (~L1118): hidden `FRESHNESS_CAP` (120s) after `last_event_ts`; 20s grace once all-complete.
- `Renderer.task_row` (~L2201): returns a single `str` — glyph + `done/total`, plus (non-compact) the one active task's `active_form`. `build_medium` calls it `compact=True` (count only); `build_wide` non-compact; `build_narrow` does **not** render tasks at all.

Sibling modules load via `importlib` because the script runs top-level, not as a package (the `themes.py` loader block, ~L19-26). `_visible_width` (L153) is the only correct column measure (ANSI-stripping, wide-char-aware); never `len()`. Nerd Font PUA glyphs must be hoisted to module-scope escape constants (the **PUA refactor rule**) or they get dropped through edit/chat round-trips. The repo already re-renders ~1s (`rainbow_step` is `int(time.time()) % …`), so a `now`-based live timer ticks at that cadence.

**In-flight coupling:** `deepen-transcript-reader` adds `claude/statusline/transcript.py` with `fold_tasks(read_events(path)) -> TaskList` and intends to repoint `TaskList.from_session` to it. At apply time, the **live source** of the `TaskList` (either `from_session`'s body or `fold_tasks`) owns the new generation/timestamp logic. The spec is written against behaviour, so it binds whichever exists.

## Goals / Non-Goals

**Goals:**
- A live task checklist: all items of the current plan generation, marked off as they complete, each with a start-to-finish timer.
- Per-task timing with clear live-vs-frozen semantics; a header Total Elapsed.
- Bounded height (≤6 content rows, active-anchored window) so a long plan never overruns the terminal.
- A decomposition that **parallel subagents can execute** with minimal cross-task coupling.

**Non-Goals:**
- No change to token/cost/context/subagent/openspec rows or colours beyond the task block.
- No persisted state; no smooth sub-render-cadence ticking.
- No new runtime dependency.

## Decisions

**D1 — Per-task timestamps; latest-run wins, clear on reopen.**
`Task` gains `started_at: float | None` and `completed_at: float | None`. On a `TaskUpdate` to `in_progress`, set `started_at` to that event's timestamp (overwrite) and clear `completed_at`. On a `TaskUpdate` to `completed`, set `completed_at`. Live duration = `now − started_at`; frozen = `completed_at − started_at`. No `started_at` ⇒ no duration. Rationale: a reopened task shows a fresh live timer; paused/resumed tasks aren't inflated by wall-clock; pending→completed jumps degrade gracefully.

**D2 — Plan Generation = the latest all-completed-delimited batch.**
While folding, track whether **all** currently-known tasks are `completed`. A `TaskCreate` seen in that state opens a new generation (discard prior, restart ids at 1). A `TaskCreate` while any task is still open appends. `from_session` returns only the latest generation. Rationale: keeps `done/total` and Total Elapsed about *this* plan; the freshness cap used to mask stale rounds, but D5's pinning would otherwise resurface them. Chosen over a time-gap split (rejected in grilling: mis-splits slow planning).

**D3 — Active-anchored window, ≤6 content rows including collapse lines.**
`select_window(tasks, budget=6)` returns the slice to render plus `done_hidden` / `more_hidden` counts. It keeps the `in_progress` item visible, biases toward upcoming pending, and counts any `+N done` / `+N more` collapse line against the budget (hard ceiling of 6 content rows). No active task ⇒ window the first pending items; all complete ⇒ window the last completed. Rationale: bounded height regardless of plan length; mirrors `mon.py` overflow clipping.

**D4 — Live timer vs frozen duration; m:ss → h:mm:ss; right-aligned column.**
`fmt_duration(secs)` → `m:ss` (`0:07`, `12:04`), rolling to `h:mm:ss` past an hour. completed items show the frozen value dim; the in_progress item shows a bright live value; pending none. Timers right-align in a fixed trailing column (width = widest shown timer); subjects truncate with `…` before that column via `_visible_width`. Rationale: scannable alignment; reuses the existing truncation discipline in `task_row`.

**D5 — Pinned visibility while any task is in_progress.**
`is_visible` returns true whenever a task is `in_progress`, regardless of `FRESHNESS_CAP`; otherwise the existing 120s cap + 20s all-complete grace apply. Rationale: a long step emits no new event, so the cap would hide the list and its live timer exactly when it matters. The live timer is itself proof of freshness.

**D6 — Header carries glyph + done/total + Total Elapsed (wall-clock span).**
`total_elapsed(tasks, now)` = earliest `started_at` → (`now` while any task is `in_progress`, else latest `completed_at`); `None` when no task ever started. Rationale: "how long this plan has been going," consistent with the now-based per-item timer; chosen over sum-of-durations to avoid a second timing semantic.

**D7 — Layout coverage: full list in wide + medium; compact line in narrow.**
Wide and medium render the header + windowed items. Narrow (no task info today) gains one compact line: glyph + `done/total` + the active task's live timer (omitted when nothing in progress), no subject. Rationale: narrow is width-constrained; the compact line still surfaces the timer.

**D8 — State glyphs as hoisted module-scope constants.**
`GLYPH_TASK_PENDING = '\ue640'`, `GLYPH_TASK_ACTIVE = '\U000f0117'`, `GLYPH_TASK_DONE = '\uf4a7'`, alongside the existing `GLYPH_TASKS` header glyph. Checkbox set, dim/bright contrast (completed dim, active bright, pending dim). Rationale: the PUA refactor rule is mandatory; escapes survive edit/chat round-trips.

**D9 — Pure view logic in `claude/statusline/tasks_view.py` (importlib-loaded).**
`fmt_duration`, `total_elapsed`, `select_window` are pure (no ANSI, no I/O) and live in a new sibling module mirroring the `themes.py` loader. `Renderer.task_row` composes ANSI/colour around their results. Rationale: isolates the testable maths, keeps `task_row` thin, and — critically — lets the parser, the helpers, the renderer, and the layout wiring be built and tested **independently and in parallel** (see Parallel Execution).

**D10 — `task_row` returns `list[str]`.**
`Renderer.task_row(tasks, width, *, compact=False) -> list[str]`. Non-compact (wide/medium) returns header line + item lines + any collapse lines; compact (narrow) returns a single-element list. Builders iterate the result into `RowSpec('content', content=line)`. The task rows carry no internal `│` divider, so **no elbow / `ups` / `downs` threading** is required — they are plain content rows like subagent rows. Rationale: fixing the return type up front is the contract that lets the renderer (D9 consumer) and the layout wiring proceed in parallel.

## Parallel Execution

This change is explicitly decomposed for parallel subagents. One **Foundation** unit lands the shared contract; then four units run concurrently with disjoint file/region ownership; a final **Verify** unit serialises.

```
                    ┌─────────────────────────────────────────────┐
   F (Foundation)   │ glyph consts + Task fields + tasks_view.py    │  serial, first
   ──────────────►  │ stubs + importlib bind + task_row signature   │
                    └─────────────────────────────────────────────┘
                                      │
        ┌───────────────┬─────────────┴───────────────┬───────────────┐
        ▼               ▼                             ▼               ▼
   A Parser        B View helpers              C Renderer       D Layout wiring   (parallel)
   TaskList.*      tasks_view.py bodies        task_row body     build_*           
   test_task_list  test_tasks_view (new)       test_task_row     (+ test_layout_*)
        └───────────────┴─────────────┬───────────────┴───────────────┘
                                      ▼
                              V (Verify)  pytest + demo + CONTEXT.md + validate   serial, last
   G (Docs: CONTEXT.md glossary) — independent, may run any time after F.
```

**Why these seams are independent:**
- **A** owns the `TaskList` class region of `statusline_command.py` and `test_task_list.py`. It implements D1/D2/D5. It does **not** touch `task_row` or builders.
- **B** owns `claude/statusline/tasks_view.py` (filling F's stubs) and a new `test_tasks_view.py`. Pure functions; touches no other file. Implements D3/D4/D6.
- **C** owns the `Renderer.task_row` method region and `test_task_row.py`. It imports B's helpers and F's glyph constants, and builds `TaskList`/`Task` fixtures **directly** (not via `from_session`), so it does not depend on A's implementation — only on F's `Task` field contract. Implements D4/D7/D8/D10.
- **D** owns `build_narrow` / `build_medium` / `build_wide` and any `test_layout_*`. It consumes `task_row`'s `list[str]` contract (D10) and emits `RowSpec`s; it can stub `task_row` to a fixed list in its own tests, so it does not block on C.
- **G** owns `CONTEXT.md` only.

**Conflict-avoidance rules for subagents:**
- All top-of-file edits to `statusline_command.py` (glyph constants, the `tasks_view` importlib block, `Task` field additions) are done **only in F**. A/C/D never edit the import region or `Task` definition.
- A, C, D edit **disjoint function regions** of `statusline_command.py`; integrate in the order A→C→D if a sequential merge is needed, but they are developed concurrently.
- Each unit owns its own test file; no two units edit the same test file.

**Foundation deliverables (the contract):**
- Glyph constants (D8) and the `Task` fields (D1) with defaults `= None`.
- `claude/statusline/tasks_view.py` with **signatures + docstrings** and trivial placeholder bodies for `fmt_duration`, `total_elapsed`, `select_window` (including the `select_window` return shape — e.g. a `WindowSlice(items, done_hidden, more_hidden)` dataclass), plus the `importlib` load+bind block in `statusline_command.py`.
- The `task_row(...) -> list[str]` signature (D10) committed (body may still return the placeholder single line until C).

## Risks / Trade-offs

- **Two task parsers drift** (`from_session` vs `deepen-transcript-reader`'s `fold_tasks`) → Mitigation: A implements against the live source at apply time; a Verify task asserts both carry the generation/timestamp semantics if both exist.
- **Window jitter** (height changes as items complete / collapse) → Accepted: bounded at 6 rows; the active-anchored window keeps the relevant slice stable.
- **Live timer appears frozen during a silent long tool call** → Accepted: identical to the existing rainbow animation; documented in proposal.
- **PUA glyphs dropped through edits** → Mitigation: D8 hoists them to escape constants in Foundation before any rendering edit.
- **Medium grows tall** (now full list vs old count) → Accepted: same 6-row ceiling as wide; narrow stays compact.
- **`select_window` off-by-one against the 6-row ceiling including collapse lines** → Mitigation: B's `test_tasks_view.py` asserts the total rendered-row count never exceeds budget across plan sizes and active positions.

## Migration Plan

1. **F** — land the contract (constants, `Task` fields, `tasks_view.py` stubs + importlib bind, `task_row` signature). `pytest -q` stays green (placeholders preserve behaviour).
2. **A / B / C / D** — concurrently implement parser, helpers, renderer, layout against the contract, each red→green in its own test file.
3. Integrate A→C→D edits to `statusline_command.py`; **G** updates `CONTEXT.md`.
4. **V** — full `pytest -q` green; `make statusline/test` eyeball across narrow→medium→wide; reconcile `fold_tasks` if present; `openspec validate task-checklist-timers`.

Rollback: revert `tasks_view.py`, the `task_row`/builder edits, the `Task` fields and constants. No data/state migration — the feature is render-time only.

## Open Questions

- None blocking. If `deepen-transcript-reader` is applied first, A's parser work moves into `fold_tasks` rather than `from_session` (same behaviour, different location).
