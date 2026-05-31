## ADDED Requirements

### Requirement: Frozen statusLine entrypoint

The statusLine command SHALL remain invocable as `python <plugin>/claude/statusline_command.py`, reading session JSON on stdin and writing the rendered statusline to stdout. The file `claude/statusline_command.py` SHALL continue to exist at that path and name, because installed `settings.json` configurations hardcode it. After the split it SHALL contain only the composition entrypoint (importing and calling `statusline.app.main`), delegating all behavior to the `statusline` package.

#### Scenario: Entrypoint still renders from stdin

- **WHEN** `python claude/statusline_command.py` is run with a valid session-info JSON payload on stdin at a terminal width ≥ `MIN_WIDTH`
- **THEN** it writes the same rendered statusline string it produced before the split

#### Scenario: Entrypoint is thin

- **WHEN** `claude/statusline_command.py` is inspected after the split
- **THEN** it defines no renderer, reader, config, or layout logic of its own and only wires `statusline.app.main` to `__main__`

### Requirement: Layered acyclic package

The statusline source SHALL be organized as a Python package under `claude/statusline/`, one module per concern, forming a single-directional acyclic dependency graph: `constants → text → {config, session, metrics, tokens, git, skills, subagents, tasks, transcript, openspec} → pill → gradient → borders → renderer → layout → app`. A module SHALL import only from modules earlier in this order; no import cycle SHALL exist among the package modules.

#### Scenario: No import cycles

- **WHEN** every module in `claude/statusline/` is imported
- **THEN** all imports resolve with no circular-import error

#### Scenario: Readers carry no render dependency

- **WHEN** the filesystem/transcript reader modules (`git`, `skills`, `subagents`, `tasks`, `transcript`, `openspec`) are imported
- **THEN** they reference no symbol from `gradient`, `borders`, `renderer`, or `layout`

### Requirement: Tests import real modules

Test files SHALL import the concrete package modules they exercise (e.g. `import statusline.borders as borders`) rather than a single flat `statusline_command` re-export namespace. The package SHALL NOT provide a catch-all re-export shim whose only purpose is to preserve the old flat namespace.

#### Scenario: A test names its module

- **WHEN** a test that exercises border math is read
- **THEN** it imports `statusline.borders` (the module that owns `BorderRenderer`), not `statusline_command`

#### Scenario: pytest resolves the package

- **WHEN** the test suite is run via `uv run pytest -q`
- **THEN** `statusline.*` modules import successfully because `pythonpath` includes the `claude` directory, with no per-test `spec_from_file_location` shim

### Requirement: Live configuration resolution

The statusline SHALL resolve configuration by calling `Config.load()` at render/command time rather than from a module-level singleton evaluated at import. No import-time global (`CONFIG`, `SOFT_LIMIT`, `MAX_WIDTH`) SHALL gate behavior; functions needing a resolved limit SHALL receive it explicitly (e.g. `build_*` taking `soft_limit`). Importing any `statusline` module SHALL NOT read environment variables or `yas.toml`.

#### Scenario: Env change takes effect without reimport

- **WHEN** `YAS_SOFT_LIMIT` is set and `render()` is called in the same process where a `statusline` module was already imported
- **THEN** the freshly set value is honored (config is resolved live, not cached at import)

#### Scenario: Importing a module is side-effect free

- **WHEN** any `statusline` package module is imported
- **THEN** no `yas.toml` read or `YAS_*` environment lookup occurs as a side effect of the import
