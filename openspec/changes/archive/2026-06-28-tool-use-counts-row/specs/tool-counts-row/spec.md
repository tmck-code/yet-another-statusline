## ADDED Requirements

### Requirement: Per-tool tool_use counting with main-vs-sub split

The system SHALL count `tool_use` blocks per tool name across the session,
splitting each tool's total into a `main` count (occurrences in the main
transcript) and a `sub` count (the sum of occurrences across all of this
session's subagent transcripts). The aggregator SHALL read only bytes already
loaded by the per-render transcript and subagent scans — it SHALL NOT introduce
an on-disk cache, an offset file, or incremental/partial reading.

#### Scenario: Tool runs in main session only

- **WHEN** the main transcript contains 3 `Edit` `tool_use` blocks and no
  subagent ran `Edit`
- **THEN** `Edit` is reported with `(main=3, sub=0)`

#### Scenario: Tool runs only inside subagents

- **WHEN** two subagent transcripts ran `Grep` 6 and 9 times respectively and the
  main transcript never ran `Grep`
- **THEN** `Grep` is reported with `(main=0, sub=15)`

#### Scenario: Both columns are always present

- **WHEN** any tool has a non-zero count on either side
- **THEN** both the `main` and the `sub` value are reported, even when one side is
  zero (e.g. `(main=4, sub=0)`)

### Requirement: Streaming dedup keeps the last write per message id

The aggregator SHALL deduplicate by `message.id` keeping the **last** occurrence
per id, counting the `tool_use` blocks of that final write, and SHALL skip lines
with no `message.id`. This is required because `tool_use` blocks carry no stable id
and streaming writes the same `message.id` several times where earlier partial
writes may contain fewer `tool_use` blocks than the final write.

#### Scenario: Final write supersedes an earlier partial

- **WHEN** a `message.id` appears first with 1 `tool_use` block and later with 2
  `tool_use` blocks
- **THEN** that message contributes 2 to the relevant tool counts (the last write),
  not 1

#### Scenario: Repeated final write is not double-counted

- **WHEN** the same `message.id` with the same 2 `tool_use` blocks is written twice
- **THEN** that message contributes 2, not 4

### Requirement: Counts are windowed to the last /clear

The aggregator SHALL count only `tool_use`-bearing messages whose `timestamp` is
at or after `SessionView.clear_epoch`. When `clear_epoch` is `None`, the aggregator
SHALL count the whole session. A subagent whose every message predates
`clear_epoch` SHALL contribute zero to all counts.

#### Scenario: Messages before /clear are excluded

- **WHEN** `clear_epoch` is set and a `tool_use` message's `timestamp` is before it
- **THEN** that message is not counted

#### Scenario: No clear marker counts the whole session

- **WHEN** `clear_epoch` is `None`
- **THEN** every `tool_use` message in the transcript is eligible for counting

### Requirement: Meta tools are excluded, Task is kept

The aggregator SHALL exclude tools in the meta set
`{TodoWrite, ExitPlanMode, AskUserQuestion}` from all counts. The `Task` tool
SHALL be counted (it represents a subagent delegation). A `Task` spawn counted in
the main column and the spawned subagent's own tool uses counted in the sub column
SHALL both be retained — the resulting double-representation across columns is
intended.

#### Scenario: TodoWrite is dropped

- **WHEN** the main transcript runs `TodoWrite` 5 times
- **THEN** `TodoWrite` does not appear in the counts

#### Scenario: Task is retained in the main column

- **WHEN** the main transcript spawns 4 subagents via `Task`
- **THEN** `Task` is reported with `main=4`

#### Scenario: Delegated work counts in the sub column independently

- **WHEN** a `Task` spawn runs in main and the spawned subagent runs `Read` twice
- **THEN** `Task` shows `main` incremented by 1 AND `Read` shows `sub` incremented
  by 2

### Requirement: MCP tool names normalize to their last segment

The aggregator SHALL normalize MCP tool names of the form `mcp__server__tool` to
their last `__`-delimited segment before counting and keying. Non-MCP names SHALL
pass through unchanged.

#### Scenario: MCP name is shortened

- **WHEN** a `tool_use` block names the tool `mcp__github__create_issue`
- **THEN** it is counted under the key `create_issue`

### Requirement: Tool-counts row is rendered wide-only under the tokens row

The system SHALL render a per-tool counts row only in the wide layout
(`build_wide`), placed in the session-totals band directly under the tokens/cost
row and before the plugins row. Narrow and medium layouts SHALL NOT render the row.
The row SHALL be full-width content with no internal divider, so it contributes no
`┬`/`┴` elbows of its own.

#### Scenario: Row appears in wide layout

- **WHEN** the wide layout is built and at least one tool has been counted since
  the last `/clear`
- **THEN** a content row of per-tool counts appears immediately after the
  tokens/cost rows

#### Scenario: Narrow and medium omit the row

- **WHEN** the narrow or medium layout is built
- **THEN** no tool-counts row is rendered

### Requirement: Row format is Name main/sub with bright/faint/dim treatment

Each entry SHALL render as the tool NAME, a space, the `main` count, a `/`, and the
`sub` count (e.g. `Bash 5/12`). The `main` count SHALL be painted bright, the `sub`
count SHALL be painted SGR-faint, and the `/` SHALL be painted dim. Both sides of
the slash SHALL always be shown.

#### Scenario: Entry shows name and both counts

- **WHEN** `Bash` has `(main=5, sub=12)`
- **THEN** the entry reads `Bash 5/12` with `5` bright, `/` dim, and `12` faint

#### Scenario: Zero sub still renders both sides

- **WHEN** `Edit` has `(main=3, sub=0)`
- **THEN** the entry reads `Edit 3/0`

### Requirement: Top-N-by-combined selection with greedy width fill and +k type overflow

Entries SHALL be ordered by combined `(main + sub)` total descending, with ties
broken alphabetically by tool name for frame-to-frame stability. The row SHALL
greedy-fill entries to the available wide content width measured via
`_visible_width` (never `len()`). When tool types remain unshown, the row SHALL
append an overflow marker `+k` where `k` is the number of additional tool TYPES not
shown (NOT the summed count of their calls). The `+k` marker SHALL NOT be clipped;
if necessary the last fitted entry is dropped to make room for it.

#### Scenario: Highest combined totals come first

- **WHEN** `Read` has combined 48 and `Bash` has combined 17
- **THEN** `Read` is ordered before `Bash`

#### Scenario: Alphabetical tie-break

- **WHEN** `Edit` and `Glob` both have the same combined total
- **THEN** `Edit` is ordered before `Glob`

#### Scenario: Overflow counts types not calls

- **WHEN** 9 tool types are counted but only 6 fit in the width and the 3 unshown
  types together account for 40 calls
- **THEN** the row ends with `+3`, not `+40`

### Requirement: Row disappears in the zero state

When there are zero counted tool uses since the last `/clear`, the system SHALL
omit both the tool-counts content row and its leading separator from the wide
layout, leaving the surrounding elbow threading (`pending_ups`) intact, exactly as
the existing conditional plugins/task/openspec rows behave.

#### Scenario: No tools counted yields no row

- **WHEN** the wide layout is built and no tool has been counted since the last
  `/clear`
- **THEN** neither the tool-counts row nor its separator is present in the layout

### Requirement: Row carries the superscript tools main/sub label

The separator above the tool-counts row SHALL carry the superscript caption `ᵗᵒᵒˡˢ ᵐᵃⁱⁿᐟˢᵘᵇ`
(the superscript rendering of `tools main/sub`) anchored at content start when
section labels are enabled (`cfg.labels`), and SHALL carry no caption when labels
are disabled.

#### Scenario: Label shown when captions enabled

- **WHEN** `cfg.labels` is true and the tool-counts row is present
- **THEN** the separator above it shows the superscript `tools main/sub` caption

#### Scenario: No label when captions disabled

- **WHEN** `cfg.labels` is false
- **THEN** the separator above the row carries no caption
