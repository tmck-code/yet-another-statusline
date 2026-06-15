## MODIFIED Requirements

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
The cap defaults to 36 visible columns when no wider space is available.

When the tool argument contains newline characters, only the first line SHALL
be used for display. Subsequent lines SHALL be discarded before the width cap
is applied.

#### Scenario: Two-line row renders duration-first with the line-1 cluster

- **WHEN** a subagent is rendered in two-line form with room for all fields
- **THEN** line 1 reads `<dur> <type> · <description>` with a right-aligned `share% · tok · model` cluster, and line 2 reads `└ <glyph> <Tool[arg]>`

#### Scenario: No t/m rate or output token field

- **WHEN** any subagent row is rendered
- **THEN** neither the t/m rate field nor the ↑output field appears

#### Scenario: Multi-line tool argument shows only first line
- **WHEN** the tool argument string contains newline characters (e.g. a multi-line Bash command)
- **THEN** only the content before the first newline is displayed; subsequent lines are not rendered
