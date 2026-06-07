## ADDED Requirements

### Requirement: No fabricated context breakdown

The statusline SHALL NOT present a context-window breakdown by system prompt,
tool definitions, plugins, or skills unless the underlying token figures are
derivable from data actually available to it. Because the stdin payload exposes
only context-window totals and a single `current_usage`, and the transcript's
`attributionSkill`/`attributionPlugin` fields attribute message usage rather
than system-prompt composition, no such by-source breakdown SHALL be displayed
at this time.

#### Scenario: No by-source breakdown is shown

- **WHEN** the statusline renders the context window
- **THEN** it does not display a system/plugins/skills token breakdown

### Requirement: Recorded feasible alternatives

The deferral SHALL record the alternatives that *are* derivable, so a future
change can implement one without re-investigating: (a) per-skill / per-plugin
cumulative token attribution from the transcript's
`attributionSkill`/`attributionPlugin` fields; (b) a structural split of current
usage into cached base (`cache_read`) versus fresh input versus output.

#### Scenario: Alternatives are documented for follow-up

- **WHEN** a future contributor revisits a context breakdown
- **THEN** the recorded alternatives and the data-availability constraint are
  available in this change's documents
