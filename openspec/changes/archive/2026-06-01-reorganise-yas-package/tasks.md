# Tasks: reorganise-yas-package

> **Working agreement — every agent, main or subagent, READ THIS FIRST.**
>
> 1. **Mark each subtask `- [x]` _immediately_ as soon as it is done** — the instant the
>    edit lands and its local check passes, edit this file and tick the box. Do **not** batch
>    ticks, do **not** wait until the end of a wave, do **not** tick ahead of finishing.
>    The checkbox state in this file is the **single source of truth** for how far the change
>    has progressed; another worker (or the human watching) reads it to decide what to pick up
>    next. A done-but-unticked task looks unstarted and will be duplicated.
> 2. **File-ownership rule for parallel work:** within a wave that runs in parallel, no two
>    workers may edit the same file concurrently. Each task below names the file(s) it owns.
>    If two pending tasks touch the same file, they belong to one worker and run in sequence.
> 3. **Wave gating:** Wave 1 tasks are mutually independent and run in parallel. Wave 2 is
>    serial and starts only after every Wave 1 box is ticked. Wave 3 is serial and starts only
>    after every Wave 2 box is ticked.
> 4. If a task turns out to be already done or not needed, tick it and note `(no-op: <reason>)`
>    inline — never leave a finished-in-effect task unticked.

## 1. Wave 0 — scaffold (serial; owns new directories and `__init__.py` files)

- [x] 1.1 Create `claude/yas/`, `claude/yas/info/`, `claude/yas/render/`.
- [x] 1.2 Create `claude/yas/__init__.py` (empty, matching `claude/statusline/__init__.py`).
- [x] 1.3 Create `claude/yas/render/__init__.py` (empty).
- [x] 1.4 Create `claude/yas/info/__init__.py` by copying `claude/statusline/info.py` and updating all `from statusline.` imports to `from yas.`.

## 2. Wave 1A — `yas/info/` reader modules (parallel with 1B and 1C; owns only `claude/yas/info/*.py` files listed here)

Copy each file to `claude/yas/info/<name>.py`, replacing every `from statusline.` with `from yas.` and `import statusline.` with `import yas.`.

- [x] 2.1 `claude/yas/info/git.py` (from `claude/statusline/git.py`)
- [x] 2.2 `claude/yas/info/openspec.py` (from `claude/statusline/openspec.py`)
- [x] 2.3 `claude/yas/info/skills.py` (from `claude/statusline/skills.py`)
- [x] 2.4 `claude/yas/info/subagents.py` (from `claude/statusline/subagents.py`)
- [x] 2.5 `claude/yas/info/tasks.py` (from `claude/statusline/tasks.py`)
- [x] 2.6 `claude/yas/info/transcript.py` (from `claude/statusline/transcript.py`)

## 3. Wave 1B — `yas/render/` modules (parallel with 1A and 1C; owns only `claude/yas/render/*.py` files listed here)

Copy each file to `claude/yas/render/<name>.py`, replacing all `from statusline.` / `import statusline.` with `from yas.` / `import yas.`.

- [x] 3.1 `claude/yas/render/gradient.py` (from `claude/statusline/gradient.py`)
- [x] 3.2 `claude/yas/render/borders.py` (from `claude/statusline/borders.py`)
- [x] 3.3 `claude/yas/render/pill.py` (from `claude/statusline/pill.py`)
- [x] 3.4 `claude/yas/render/text.py` (from `claude/statusline/text.py`)
- [x] 3.5 `claude/yas/render/metrics.py` (from `claude/statusline/metrics.py`)

## 4. Wave 1C — top-level `yas/` modules (parallel with 1A and 1B; owns only `claude/yas/*.py` files listed here)

Copy each file to `claude/yas/<name>.py`, replacing all `from statusline.` / `import statusline.` with `from yas.` / `import yas.`. Additionally, update any intra-package imports that now point to a subpackage path (e.g. `from yas.borders` → `from yas.render.borders`, `from yas.gradient` → `from yas.render.gradient`, `from yas.git` → `from yas.info.git`, etc.).

- [x] 4.1 `claude/yas/constants.py` (from `claude/statusline/constants.py`)
- [x] 4.2 `claude/yas/session.py` (from `claude/statusline/session.py`)
- [x] 4.3 `claude/yas/config.py` (from `claude/statusline/config.py`)
- [x] 4.4 `claude/yas/tokens.py` (from `claude/statusline/tokens.py`)
- [x] 4.5 `claude/yas/themes.py` (from `claude/statusline/themes.py`)
- [x] 4.6 `claude/yas/renderer.py` (from `claude/statusline/renderer.py`; imports `yas.render.borders`, `yas.render.gradient`, `yas.render.pill`, `yas.render.text`, `yas.render.metrics`, and `yas.info.*` for data types)
- [x] 4.7 `claude/yas/layout.py` (from `claude/statusline/layout.py`)
- [x] 4.8 `claude/yas/app.py` (from `claude/statusline/app.py`)

## 5. Wave 2 — cutover external callers (serial, gated on Waves 1A–1C all ticked)

Verify all Wave 1 boxes are ticked before starting this wave.

- [x] 5.1 Update `claude/statusline_command.py`: change `from statusline.app import main` → `from yas.app import main`.
- [x] 5.2 Update `claude/mon.py`: change `from statusline.app import render, resolve_theme` → `from yas.app import …` and `from statusline.constants import MIN_WIDTH` → `from yas.constants import MIN_WIDTH`.
- [x] 5.3 Update `test/conftest.py`: replace all `import statusline.*` with `import yas.*` (six module references). The `_SRC` path to `statusline_command.py` is unchanged.
- [x] 5.4 Update all remaining test files — replace every `from statusline.` / `import statusline.` / `import statusline_command` (where it re-imports via the shim) with the `yas.*` equivalent. Files known to need updates: `test_pure_helpers.py`, `test_plugins_skills.py`, `test_task_row.py`, `test_layout_seam.py`, `test_layout_subagent_rows.py`, `test_model_section.py`, `test_session_elapsed.py`, `test_subagent_rows.py`, `test_themes.py`, `test_info.py`, and any others containing `statusline`.
- [x] 5.5 Update `ops/demo.py`: change the two hardcoded path constants from `claude/statusline/…` to `claude/yas/…`.
- [x] 5.6 Copy `claude/statusline/session-info-example.json` to `claude/yas/session-info-example.json`.
- [x] 5.7 Run `uv run pytest -q` and confirm the full suite is green before proceeding to Wave 3.

## 6. Wave 3 — delete old package and final verification (serial, gated on Wave 2 all ticked)

- [x] 6.1 Run `grep -r "from statusline\|import statusline" claude/ test/ ops/` and confirm zero hits.
- [x] 6.2 Delete the old package: `git rm -r claude/statusline/`.
- [x] 6.3 Run `uv run pytest -q` — must be green.
- [x] 6.4 Run `make statusline/test` (or `uv run python ops/demo.py`) and eyeball elbow/pill alignment across the narrow/medium/wide thresholds.
- [x] 6.5 Update `CONTEXT.md` Module map: rename `claude/statusline/` references to `claude/yas/` and add the two subpackages.
