## ADDED Requirements

### Requirement: Activity verb derivation

The activity continuation's verb SHALL be derived from the latest assistant
message in the subagent transcript by preferring the last `tool_use` content
block in that message. When the message contains no `tool_use` block, the verb
SHALL fall back to the first non-empty line of the last `text` block, passed
through the untrusted-input sanitizer. A `thinking` block SHALL continue to
render as the thinking indicator. The system SHALL NOT render a contentless
`(replying)` placeholder when text content is available.

The rendered text snippet SHALL reuse the existing activity truncation cap of
36 visible columns (measured via the visible-width helper), appending a single
`…` when it exceeds that cap.

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

#### Scenario: Long text snippet truncates at the activity cap

- **WHEN** the first non-empty line of the text block exceeds 36 visible columns
- **THEN** the snippet is truncated to the cap with a trailing `…`

#### Scenario: Thinking block is unchanged

- **WHEN** the latest assistant message's selected block is a `thinking` block
- **THEN** the activity continuation shows the thinking indicator
