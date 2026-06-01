## MODIFIED Requirements

### Requirement: Layered acyclic package

The statusline source SHALL be organized as a Python package under `claude/statusline/`, one module per concern, forming a single-directional acyclic dependency graph: `constants → text → {config, session, metrics, tokens, git, skills, subagents, tasks, transcript, openspec} → info → pill → gradient → borders → renderer → layout → app`. A module SHALL import only from modules earlier in this order; no import cycle SHALL exist among the package modules. The `info` module (`SessionView`) SHALL be the gather seam between the readers and the render layer: `layout` SHALL obtain derived session state from `info` and SHALL NOT import the reader modules (`git`, `skills`, `subagents`, `tasks`, `transcript`, `openspec`) directly.

#### Scenario: No import cycles

- **WHEN** every module in `claude/statusline/` is imported
- **THEN** all imports resolve with no circular-import error

#### Scenario: Readers carry no render dependency

- **WHEN** the filesystem/transcript reader modules (`git`, `skills`, `subagents`, `tasks`, `transcript`, `openspec`) are imported
- **THEN** they reference no symbol from `gradient`, `borders`, `renderer`, or `layout`

#### Scenario: Layout consumes the gather seam, not the readers

- **WHEN** `claude/statusline/layout.py` is inspected after this change
- **THEN** it imports `statusline.info` for derived session state and imports none of `git`, `skills`, `subagents`, `tasks`, `transcript`, or `openspec` directly
