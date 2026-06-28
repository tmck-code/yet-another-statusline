## ADDED Requirements

### Requirement: Tool-counts gather field

`SessionView` SHALL expose a `tool_counts` `@cached_property` returning a
`ToolCounts` value that holds, per tool name, the `(main, sub)` `tool_use` counts
and the total number of distinct tool types. It SHALL be constructed from the main
transcript, the subagent cohort, and `clear_epoch` — all fields already available
on the view — and SHALL perform no I/O beyond reopening those same transcript
files. As a `@cached_property`, it SHALL be computed at most once per view and
SHALL NOT be evaluated when a render path never reads it (narrow/medium). The
`info` layer SHALL NOT import `renderer` or `layout` to provide it.

#### Scenario: Field exposes per-tool main/sub counts

- **WHEN** a `SessionView` is constructed and `tool_counts` is read
- **THEN** it returns a `ToolCounts` whose per-tool entries each carry a `main` and
  a `sub` count derived from the main transcript and the subagent cohort
  respectively

#### Scenario: Field is lazy

- **WHEN** a narrow or medium render is produced without reading `tool_counts`
- **THEN** the tool-counts aggregation is never computed

#### Scenario: Field respects the clear window

- **WHEN** `clear_epoch` is set on the view
- **THEN** `tool_counts` reflects only `tool_use` messages at or after that epoch
