## MODIFIED Requirements

### Requirement: Frozen statusLine entrypoint

The statusLine command SHALL remain invocable as `python <plugin>/claude/statusline_command.py`, reading session JSON on stdin and writing the rendered statusline to stdout. The file `claude/statusline_command.py` SHALL continue to exist at that path and name, because installed `settings.json` configurations hardcode it. After the reorganisation it SHALL contain only the composition entrypoint (importing and calling `yas.app.main`), delegating all behaviour to the `yas` package.

#### Scenario: Entrypoint still renders from stdin

- **WHEN** `python claude/statusline_command.py` is run with a valid session-info JSON payload on stdin at a terminal width ≥ `MIN_WIDTH`
- **THEN** it writes the same rendered statusline string it produced before the reorganisation

#### Scenario: Entrypoint is thin

- **WHEN** `claude/statusline_command.py` is inspected after the reorganisation
- **THEN** it defines no renderer, reader, config, or layout logic of its own and only wires `yas.app.main` to `__main__`

### Requirement: Layered acyclic package

The statusline source SHALL be organised as a Python package under `claude/yas/`, forming a single-directional acyclic dependency graph. The package SHALL contain two subpackages:

- `yas/info/` — the data-gather layer: `git`, `openspec`, `skills`, `subagents`, `tasks`, `transcript` (readers), with `SessionView` as the public face via `__init__.py`.
- `yas/render/` — renderer building-blocks: `gradient`, `borders`, `pill`, `text`, `metrics`.

Top-level modules (cross-cutting): `constants`, `session`, `config`, `tokens`, `themes`, `renderer`, `layout`, `app`.

The DAG order SHALL be: `constants → text → {config, session, metrics, tokens} → {info/*, render/*} → renderer → layout → app`. A module SHALL import only from modules earlier in this order; no import cycle SHALL exist.

#### Scenario: No import cycles

- **WHEN** every module in `claude/yas/` (including subpackages) is imported
- **THEN** all imports resolve with no circular-import error

#### Scenario: Readers carry no render dependency

- **WHEN** the filesystem reader modules under `yas/info/` (`git`, `skills`, `subagents`, `tasks`, `transcript`, `openspec`) are imported
- **THEN** they reference no symbol from `yas.render`, `yas.renderer`, or `yas.layout`

#### Scenario: Subpackage public face

- **WHEN** a caller writes `from yas.info import SessionView`
- **THEN** the import resolves without referencing a submodule explicitly, because `SessionView` is exported from `yas/info/__init__.py`

### Requirement: Tests import real modules

Test files SHALL import the concrete package modules they exercise (e.g. `import yas.borders as borders`) rather than a single flat `statusline_command` re-export namespace. The package SHALL NOT provide a catch-all re-export shim whose only purpose is to preserve the old flat namespace.

#### Scenario: A test names its module

- **WHEN** a test that exercises border math is read
- **THEN** it imports `yas.render.borders` (the module that owns `BorderRenderer`), not `statusline_command`

#### Scenario: pytest resolves the package

- **WHEN** the test suite is run via `uv run pytest -q`
- **THEN** `yas.*` modules import successfully because `pythonpath` includes the `claude` directory, with no per-test `spec_from_file_location` shim

### Requirement: Live configuration resolution

The statusline SHALL resolve configuration by calling `Config.load()` at render/command time rather than from a module-level singleton evaluated at import. No import-time global SHALL gate behaviour; functions needing a resolved limit SHALL receive it explicitly. Importing any `yas` module SHALL NOT read environment variables or `yas.toml`.

#### Scenario: Env change takes effect without reimport

- **WHEN** `YAS_SOFT_LIMIT` is set and `render()` is called in the same process where a `yas` module was already imported
- **THEN** the freshly set value is honoured (config is resolved live, not cached at import)

#### Scenario: Importing a module is side-effect free

- **WHEN** any `yas` package module is imported
- **THEN** no `yas.toml` read or `YAS_*` environment lookup occurs as a side effect of the import
