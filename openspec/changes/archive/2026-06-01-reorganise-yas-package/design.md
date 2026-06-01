## Context

`claude/statusline/` contains 21 flat Python files. With the addition of `info.py` (the `SessionView` gather seam) the three-layer structure — data-gather readers, renderer building-blocks, layout/app — is architecturally present but invisible in the directory tree. This change makes the grouping explicit by introducing two subpackages while keeping everything that is cross-cutting at the top level.

## Goals / Non-Goals

**Goals:**
- Rename the package root from `claude/statusline/` to `claude/yas/` so the top-level import prefix matches the project name.
- Group the six data-gather readers under `yas/info/` with `SessionView` as the subpackage's public face (`__init__.py`).
- Group the five renderer support modules under `yas/render/`.
- Reduce the flat top-level file count from 21 to 8.
- All import sites outside the package (`statusline_command.py`, `mon.py`, tests, `ops/demo.py`) updated to `yas.*`.

**Non-Goals:**
- No change to rendered output, runtime contracts, config, themes, or demo scenarios.
- No change to the six readers' internals or any module's behaviour.
- No compat shim for the old `statusline.*` prefix — this is a first-party, single-repo rename.

## Decisions

### D1: `renderer.py` stays top-level

`renderer.py` imports data types from all six gather readers (`GitInfo`, `LoadedSkills`, etc.) directly, not through `SessionView`. Moving it into `yas/render/` would create a `render/ → info/` cross-subpackage dependency that undermines the visual grouping goal. Keeping it top-level avoids that and is honest about its cross-cutting nature.

### D2: `tokens.py` stays top-level

`tokens.py` is consumed by three layers: `yas/info/__init__.py` (`compute_session_cost`), `renderer.py` (`TokenAccounting`, `TokenRate`), and `app.py` (`TickRecord`, `TokenLog`, `compute_day_cost`). Moving it into `info/` would create a `render/ → info/tokens` import, so it stays flat alongside the other cross-cutting modules.

### D3: `info.py` becomes `yas/info/__init__.py`

The subpackage *is* the gather seam. `SessionView` is the only symbol callers import from this layer; the six reader modules are internal detail. Promoting `info.py` to `__init__.py` means `from yas.info import SessionView` works without an extra module level, matching the stdlib convention (e.g. `from pathlib import Path`).

### D4: `yas/render/__init__.py` is empty

No single symbol dominates `render/` the way `SessionView` dominates `info/`. Callers (`renderer.py` exclusively) import from specific submodules (`yas.render.gradient`, `yas.render.borders`, etc.). An empty `__init__.py` is sufficient.

### D5: Additive creation, then cutover

Workers create `claude/yas/` alongside the still-intact `claude/statusline/`. The test suite continues to pass against the old package until a single serial cutover step updates all external callers and `session-info-example.json` moves. The old directory is deleted only after the suite is green against `yas.*`.

This lets the fan-out waves (subpackage creation) proceed in parallel without leaving the suite broken mid-way.

## Risks / Trade-offs

- **Crooked borders / pill misalignment** → visual-only regressions that unit tests miss. Mitigation: run `make statusline/test` (the demo) after the cutover step and eyeball elbow/pill alignment across narrow/medium/wide thresholds.
- **Missed import site** → an overlooked `statusline.*` reference causes an `ImportError` at runtime. Mitigation: `grep -r "from statusline\|import statusline" .` in the verify step catches any stragglers before the old directory is deleted.
- **Transient duplication** → `claude/statusline/` and `claude/yas/` coexist during Wave 1. Mitigation: Wave 1 is additive-only; the old package remains untouched until the cutover commit.

## Migration Plan

1. **Wave 1 (parallel):** Create `claude/yas/` with updated imports; create `yas/info/` and `yas/render/` subpackages. Old `claude/statusline/` untouched — suite stays green.
2. **Wave 2 (serial):** Cutover: update `statusline_command.py`, `mon.py`, all tests, `ops/demo.py` to `yas.*`; move `session-info-example.json`. Run `uv run pytest -q` — must be green.
3. **Wave 3 (serial):** Delete `claude/statusline/`. Run `uv run pytest -q` + `make statusline/test`. Confirm green.

Rollback before Wave 3 is deleting `claude/yas/` and reverting the external-caller edits. After Wave 3 (deletion), rollback is `git checkout HEAD claude/statusline/`.
