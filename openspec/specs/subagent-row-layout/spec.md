# subagent-row-layout Specification

## Purpose

Define the field set and layout of an individual subagent row: the two-line form (duration-first line 1 with a right-aligned `share% · tok · model` cluster and an activity-continuation line 2), the shedding order under width pressure, and the one-line collapse form. The t/m rate and ↑output fields are removed from both forms.

## Requirements

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

### Requirement: Activity verb derivation

The activity continuation's verb SHALL be derived from the latest assistant
message in the subagent transcript by preferring the last `tool_use` content
block in that message. When the message contains no `tool_use` block, the verb
SHALL fall back to the first non-empty line of the last `text` block, passed
through the untrusted-input sanitizer. A `thinking` block SHALL continue to
render as the thinking indicator. The system SHALL NOT render a contentless
`(replying)` placeholder when text content is available.

The rendered text snippet (and tool-arg) SHALL use a dynamic activity
truncation cap that grows with the available line-2 width, measured via the
visible-width helper, appending a single `…` when the content exceeds that cap.
The cap defaults to 36 visible columns when no wider space is available and for
callers without width context (the floor); the line-2 renderer passes
`min(100, available_width)`, so the cap rises up to a ceiling of 100 visible
columns when the terminal has spare horizontal space.

#### Scenario: Tool use wins over trailing text in the same message

- **WHEN** the latest assistant message contains both a `tool_use` block and a
  trailing `text` block
- **THEN** the activity continuation shows the tool verb (`<glyph> Tool[arg]`),
  not the text snippet

#### Scenario: Text-only message shows a snippet instead of bare replying

- **WHEN** the latest assistant message ends with a `text` block and contains
  no `tool_use` block
- **THEN** the activity continuation shows the replying glyph followed by the
  first non-empty line of that text, sanitized

#### Scenario: Snippet within the available width is shown in full

- **WHEN** the first non-empty line of the text block exceeds 36 visible columns
  but fits within the available line-2 width (≤ 100 visible columns)
- **THEN** the snippet is shown in full with no trailing `…`

#### Scenario: Long text snippet truncates at the dynamic cap

- **WHEN** the first non-empty line of the text block exceeds the cap derived
  from the available line-2 width (`min(100, available_width)`)
- **THEN** the snippet is truncated to that cap with a trailing `…`

#### Scenario: Snippet beyond the ceiling truncates at 100 columns

- **WHEN** the first non-empty line of the text block exceeds the 100-column
  ceiling
- **THEN** the snippet is truncated to 100 visible columns with a trailing `…`

#### Scenario: Thinking block is unchanged

- **WHEN** the latest assistant message's selected block is a `thinking` block
- **THEN** the activity continuation shows the thinking indicator
