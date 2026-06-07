## ADDED Requirements

### Requirement: Two-line row field set

A subagent rendered in two-line form SHALL place the elapsed duration at the front of line 1, followed by the agent type, a `·` separator, and the description. Line 1 SHALL end with a right-aligned cluster of `share% · tok · model`. Line 2 SHALL show only the activity continuation (`└` + activity glyph + tool/verb), with no right-aligned metrics. The t/m rate and ↑output fields SHALL NOT appear in either line.

#### Scenario: Two-line row renders duration-first with the line-1 cluster

- **WHEN** a subagent is rendered in two-line form with room for all fields
- **THEN** line 1 reads `<dur> <type> · <description>` with a right-aligned `share% · tok · model` cluster, and line 2 reads `└ <glyph> <Tool[arg]>`

#### Scenario: No t/m rate or output token field

- **WHEN** any subagent row is rendered
- **THEN** neither the t/m rate field nor the ↑output field appears

### Requirement: Line-1 cluster shedding

When line 1 lacks room for the full `share% · tok · model` cluster, the description SHALL truncate first. If the cluster still does not fit, fields SHALL shed in order: share% first, then tok. The model and the front duration SHALL always be retained.

#### Scenario: Description truncates before the cluster sheds

- **WHEN** line 1 is too wide for the full description plus cluster
- **THEN** the description truncates with an ellipsis while the full cluster is retained

#### Scenario: Cluster sheds share% then tok under width pressure

- **WHEN** the truncated description plus full cluster still exceeds the width
- **THEN** share% is dropped first, then tok, while model and the front duration remain

### Requirement: One-line collapse form

A subagent rendered in one-line (collapsed) form SHALL omit the ↑output field. Its remaining structure — leading marker, agent type, model, activity verb, and the right-aligned token and duration fields — SHALL be unchanged.

#### Scenario: One-line form drops output but keeps token and duration

- **WHEN** a subagent is rendered in one-line collapsed form
- **THEN** the ↑output field is absent and the token count and duration fields remain
