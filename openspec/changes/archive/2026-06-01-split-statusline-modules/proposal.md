## Why

`claude/statusline_command.py` is a 3,200-line flat module: every symbol — config resolution, session-JSON intake, token accounting, six filesystem readers, the three-layer painter, and the layout pipeline — lives in one namespace that ~40 test files reach into via `import statusline_command as sl`. The interface is as large as the implementation, which is the definition of a shallow module: there are no real seams, the file is hard to navigate, and the I/O readers can only be tested through the whole monolith. Splitting it into a layered package turns each band into an independently-importable module with its own test surface, and reduces the plugin entrypoint to a thin composition root.

## What Changes

- Introduce a layered `claude/statusline/` package (the directory already exists with an empty `__init__.py`) holding one module per concern, arranged as an acyclic dependency DAG: `constants → text → {config, session, metrics, tokens, 6 readers} → pill → gradient → borders → renderer → layout → app`.
- Reduce `claude/statusline_command.py` to a ~3-line entrypoint that imports and calls `statusline.app.main`. **Its filename is frozen** — `settings.json` hardcodes `.../claude/statusline_command.py`, so the file must stay put and stay named that or every installed plugin user breaks.
- **BREAKING (internal test API only):** repoint all ~40 test files from the flat `import statusline_command as sl` namespace to the real modules, module-qualified (`import statusline.borders as borders`). No public/runtime contract changes.
- Remove the import-time global singletons `CONFIG`, `SOFT_LIMIT`, `MAX_WIDTH`. `render()` resolves `Config.load()` live (matching what `main()` and `resolve_theme()` already do, and fixing the documented live-vs-cached inconsistency); `build_*` take explicit `soft_limit`.
- Add `[tool.pytest.ini_options] pythonpath = ["claude"]` so `statusline.*` and `statusline_command` resolve under pytest, and **delete two bespoke import shims**: conftest's `spec_from_file_location` block and the `__file__`-relative themes loader (replaced by a normal `from statusline.themes import ...`).
- Repoint `claude/mon.py` to `from statusline.app import render, resolve_theme` + `from statusline.constants import MIN_WIDTH` (dropping its manual `sys.path.insert`).
- Structure the work so the per-module extractions run as **independent parallel subagents**: the DAG is published up front, each leaf/mid module is a self-contained extraction job (move code → repoint its test file → green), and only the entrypoint-collapse step serializes at the end.

## Capabilities

### New Capabilities
- `statusline-packaging`: the architectural contract for how the statusline source is organized — the frozen entrypoint filename, the layered acyclic package, the live (non-import-time) configuration resolution, and the test-imports-real-modules rule. Encodes invariants future changes must respect.

### Modified Capabilities
<!-- None. The precedence behaviour, yas.toml schema, per-model overrides, and config-error row in statusline-config are unchanged; Config is still built once and frozen per invocation, only its construction site moves from import-time global to live call. -->

## Impact

- **Code:** `claude/statusline_command.py` (gutted to entrypoint), new modules under `claude/statusline/`, `claude/mon.py` (repointed), `pyproject.toml` (pytest pythonpath).
- **Tests:** ~40 files in `test/` repointed to `statusline.*`; `test/conftest.py` simplified (spec shim removed).
- **Distribution:** none — the `yas` plugin ships the whole `claude/` tree and neither `plugin.json` nor `marketplace.json` enumerates files, so new modules ship automatically.
- **Runtime/public API:** none — `python claude/statusline_command.py` still reads session JSON on stdin and writes the rendered statusline; `render`/`resolve_theme`/`MIN_WIDTH` remain importable (from `statusline.app`/`statusline.constants`).
- **Docs:** `CONTEXT.md` gains a "Module map" section naming each module against its canonical concept.
