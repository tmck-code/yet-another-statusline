## Why

The `claude/statusline/` package has grown to 21 flat Python files, making it hard to see at a glance which modules belong together. Grouping them into `yas/info/` (data-gather readers) and `yas/render/` (renderer building-blocks) reduces the flat list to 8 top-level files and makes the three-layer structure (gather → render support → layout/app) visible in the directory tree.

## What Changes

- **BREAKING** Rename `claude/statusline/` → `claude/yas/`; all internal imports change from `statusline.*` to `yas.*`.
- Move the six data-gather readers (`git`, `openspec`, `skills`, `subagents`, `tasks`, `transcript`) into `claude/yas/info/`; promote `info.py` to `claude/yas/info/__init__.py` so `from yas.info import SessionView` continues to work.
- Move the five renderer support modules (`gradient`, `borders`, `pill`, `text`, `metrics`) into `claude/yas/render/` with an empty `__init__.py`.
- Keep at `claude/yas/` top-level: `app`, `config`, `constants`, `layout`, `renderer`, `session`, `themes`, `tokens`.
- Update all import sites outside the package: `claude/statusline_command.py`, `claude/mon.py`, all test files, and `ops/demo.py` (two hardcoded paths).
- `session-info-example.json` moves with the package to `claude/yas/`.

## Capabilities

### New Capabilities

*(none — this is a structural reorganisation with no new runtime behaviour)*

### Modified Capabilities

- `statusline-packaging`: package root changes from `claude/statusline/` to `claude/yas/`; the acyclic DAG gains two subpackages (`info/`, `render/`); import prefix changes from `statusline.` to `yas.`; entrypoint shim (`statusline_command.py`) updates its single import.

## Impact

- Every `statusline.*` import in the repo becomes `yas.*` (package modules, tests, `mon.py`, `statusline_command.py`).
- `ops/demo.py` path constants `claude/statusline/…` → `claude/yas/…`.
- `test/conftest.py` path to `statusline_command.py` is unchanged (the shim file stays at `claude/statusline_command.py`).
- No change to rendered output, runtime contracts, config, themes, or the demo scenarios.
- No new third-party dependencies.
