## ADDED Requirements

### Requirement: Phase list parsed from workflow script
The system SHALL parse phase titles from the workflow script file located at `workflows/scripts/*-<runId>.js` using a regex on the `meta.phases` array. Parsing SHALL extract each `title:` string in order. When no script file exists or parsing fails, the phase list SHALL be empty and the system SHALL fall back to the existing `[phase]` bracket display. Parsing SHALL never raise an exception.

#### Scenario: Phases extracted from script meta block
- **WHEN** a workflow script exists at `workflows/scripts/*-<runId>.js` containing a `meta.phases` array with `title:` fields
- **THEN** `RunningWorkflow.phases` is populated with the titles in order

#### Scenario: Missing script yields empty phase list
- **WHEN** no matching script file exists in `workflows/scripts/`
- **THEN** `RunningWorkflow.phases` is `[]` and the header falls back to `[phase]` bracket style

#### Scenario: Malformed script yields empty phase list
- **WHEN** the script file exists but has no parseable `phases:` array
- **THEN** `RunningWorkflow.phases` is `[]` and no exception is raised

### Requirement: Inline phase list in workflow header
When `RunningWorkflow.phases` is non-empty, the workflow header SHALL render phases inline as a dot-separated list after the workflow name, using the form `▸  <name>  P1 · P2 · P3`. Each phase title SHALL be rendered in a dim colour. The phase matching `run.phase` (the current phase from the completion JSON) SHALL be rendered in a highlight colour with a `❯` prefix. When `run.phase` is empty (live run), all phases SHALL be dimmed with no `❯` marker. The workflow name SHALL be middle-ellipsised to fit the available width after the glyph and phase list. When the phase list itself is too wide, it SHALL be truncated with `…` rather than further truncating the name.

#### Scenario: All phases shown with current highlighted post-completion
- **WHEN** `run.phases = ['Discover', 'Scan', 'Verify']` and `run.phase = 'Scan'`
- **THEN** the header renders `▸  <name>  Discover · ❯Scan · Verify` with `❯Scan` in highlight colour and the others dimmed

#### Scenario: All phases shown dimmed during live run
- **WHEN** `run.phases = ['Discover', 'Scan']` and `run.phase = ''`
- **THEN** the header renders `▸  <name>  Discover · Scan` with both phases dimmed and no `❯` marker

#### Scenario: Empty phases falls back to bracket style
- **WHEN** `run.phases = []` and `run.phase = 'Scan'`
- **THEN** the header renders `▸  <name>  [Scan]` (existing bracket form)

#### Scenario: Phase list truncated when too wide
- **WHEN** the phase list plus name exceed `content_width`
- **THEN** the phase list is truncated with `…` and the name is preserved at its minimum width
