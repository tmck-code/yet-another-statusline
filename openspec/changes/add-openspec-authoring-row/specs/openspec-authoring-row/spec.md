## ADDED Requirements

### Requirement: Authoring-stage row eligibility

A change directory under `openspec/changes/` SHALL be rendered as an
authoring-stage row when, and only when, it is a directory, is not `archive` (nor
under it), does not have a name beginning with `.`, and contains **no**
`tasks.md`. A change that has a `tasks.md` SHALL NOT produce an authoring row
under any circumstance, including when that `tasks.md` contains zero checkboxes —
such a change SHALL remain invisible exactly as it is today.

#### Scenario: Scaffolded change with no artifacts is visible

- **WHEN** `openspec/changes/add-thing/` exists containing only `.openspec.yaml`
- **THEN** an authoring row is rendered for `add-thing`

#### Scenario: A change with tasks.md renders as a task bar, not an authoring row

- **WHEN** `openspec/changes/add-thing/tasks.md` exists with at least one checkbox
- **THEN** no authoring row is rendered for `add-thing`
- **AND** the existing task-progress bar is rendered for it instead

#### Scenario: Empty tasks.md stays invisible

- **WHEN** `openspec/changes/add-thing/tasks.md` exists but contains no checkbox lines
- **THEN** neither an authoring row nor a task bar is rendered for `add-thing`

#### Scenario: Archived changes are excluded

- **WHEN** `openspec/changes/archive/2026-01-01-old-thing/` exists without a `tasks.md`
- **THEN** no authoring row is rendered for it

#### Scenario: Handover when tasks.md lands

- **WHEN** a change that was rendering an authoring row gains a `tasks.md` with
  checkboxes
- **THEN** on the next render the authoring row is gone and the task-progress bar
  for that change is present in its place

### Requirement: Four stage slots with done/active/pending semantics

An authoring row SHALL render exactly four stage slots, in the fixed order
`proposal`, `design`, `deltas`, `tasks`. Each slot SHALL show `GLYPH_TASK_DONE`
when done, `GLYPH_TASK_ACTIVE` when active, and `GLYPH_TASK_PENDING` otherwise,
using the renderer's success, warning and label colours respectively.

`proposal` and `design` SHALL be done iff `proposal.md` / `design.md` exist in the
change directory. `deltas` SHALL be done iff the count of `specs/*/spec.md` files
is greater than zero and at least the declared delta total. `tasks` SHALL never be
done, since its completion removes the row.

Exactly one slot SHALL be active: the first slot in order that is not done. All
slots after the active one SHALL be pending.

#### Scenario: Freshly scaffolded change

- **WHEN** the change directory contains no `proposal.md`, no `design.md` and no spec deltas
- **THEN** the `proposal` slot is active and `design`, `deltas` and `tasks` are pending

#### Scenario: Proposal landed

- **WHEN** `proposal.md` exists and `design.md` does not
- **THEN** the `proposal` slot is done and the `design` slot is active

#### Scenario: Deltas partially landed

- **WHEN** `proposal.md` and `design.md` exist, 2 of a declared 3 spec deltas exist
- **THEN** `proposal` and `design` are done, `deltas` is active, and `tasks` is pending

#### Scenario: All deltas landed, tasks in flight

- **WHEN** `proposal.md`, `design.md` and all declared spec deltas exist and `tasks.md` does not
- **THEN** `proposal`, `design` and `deltas` are done and `tasks` is active

### Requirement: Delta denominator derived from the proposal's capabilities

The `deltas` slot SHALL display `deltas N/M`, where `N` is the count of
`specs/*/spec.md` files present and `M` is the number of capability bullets
declared under the `## Capabilities` heading of `proposal.md` (both the New and
Modified subsections). When `proposal.md` does not exist or declares no
capability bullets, `M` SHALL render as `?`. When `N` exceeds `M`, `M` SHALL be
clamped up to `N` so the displayed fraction is never greater than one. Counts
above 9 SHALL be clamped to `9` so the label width never changes.

#### Scenario: Denominator from proposal capabilities

- **WHEN** `proposal.md` declares 1 new capability and 2 modified capabilities and
  1 spec delta file exists
- **THEN** the `deltas` slot label reads `deltas 1/3`

#### Scenario: Unknown denominator before the proposal exists

- **WHEN** no `proposal.md` exists
- **THEN** the `deltas` slot label reads `deltas 0/?`

#### Scenario: More deltas than declared

- **WHEN** 4 spec delta files exist but only 3 capability bullets were declared
- **THEN** the label reads `deltas 4/4` and the `deltas` slot is done

### Requirement: Fixed-width right-anchored stage block

The stage block's visible width SHALL depend only on the box width and the degrade
tier — never on the change name, nor on which slot is active, nor on the delta
counts. Each stage label SHALL be truncated and left-justified to a constant
per-slot width. The stage block SHALL be anchored to the right of the row so that
its last cell abuts the right-hand gutter.

Consequently, every authoring row rendered at a given box width SHALL resolve to
the same set of divider columns, so multiple concurrently-authored changes stack
with their stage cells vertically aligned.

#### Scenario: Alignment across differing names and stages

- **WHEN** three authoring rows with names of markedly different lengths and three
  different lifecycle stages are rendered at the same box width
- **THEN** all three rows report identical divider columns
- **AND** each row's rendered `┊` characters sit at exactly those columns

#### Scenario: Label width is state-invariant

- **WHEN** the same change is rendered with `deltas 0/3` and again with `deltas 3/3`
- **THEN** both rows have the same visible width and the same divider columns

### Requirement: Dashed dividers carry the border gradient and real elbows

Each of the four `GLYPH_WF_DIVIDER` (`┊`) characters in an authoring row SHALL be
coloured with the frame's border gradient at that divider's own column, using the
same gradient accessor and the same `col - 1` indexing convention the layout
already uses for the workflow column divider. They SHALL NOT render in a flat or
dim style.

Each divider SHALL additionally be threaded into the surrounding frame as a real
elbow: a `┬` on the separator immediately above the authoring group and a `┴` on
the separator or bottom border immediately below it. This is a deliberate
departure from the convention that dashed dividers float free of the frame.

#### Scenario: Divider colour matches the border gradient

- **WHEN** an authoring row is rendered at a given box width and fill
- **THEN** the escape sequence immediately preceding each `┊` equals the gradient
  colour for that divider's column at the same width and fill

#### Scenario: Elbows line up with the dividers

- **WHEN** an authoring group is rendered inside the openspec box
- **THEN** the separator above it carries a `┬` at every divider column
- **AND** the separator or bottom border below it carries a `┴` at the same columns

### Requirement: One-space right gutter

An authoring row's content SHALL be built to exactly `width - 4` visible columns,
so that the box's own content padding leaves exactly one space between the `tasks`
label and the right-hand border. The row SHALL NOT achieve the gutter by
appending a literal trailing space.

#### Scenario: Exactly one space before the right border

- **WHEN** an authoring row is rendered at any box width in the wide regime
- **THEN** the rendered line is exactly `width` visible columns
- **AND** the character immediately left of the closing `│` is a space, and the
  character left of that is the last character of the `tasks` label

### Requirement: Name cell absorbs slack with an ellipsis truncation and a floor

The name cell SHALL receive all horizontal slack left over after the fixed-width
stage block. When the name is shorter than the cell it SHALL be padded to fill it;
when longer it SHALL be truncated and terminated with `ELLIPSIS`. All fit and
truncation decisions SHALL be measured with the renderer's visible-width helper,
never `len()`.

The name cell SHALL NOT be shrunk below a floor of 15 visible columns to make room
for full stage labels.

#### Scenario: Short name is padded

- **WHEN** a change named `fix-typo` is rendered in a wide box
- **THEN** the name cell is padded with spaces up to the name/stage divider

#### Scenario: Long name is truncated with an ellipsis

- **WHEN** a change whose name exceeds the name cell width is rendered
- **THEN** the name is truncated and its last visible character is `ELLIPSIS`
- **AND** the row's divider columns are unchanged from those of a short-named row

### Requirement: Glyph-only degrade below the name-cell floor

The stage cells SHALL shed their labels and render as bare glyphs whenever the
full-label stage block would push the name cell below its 15-column floor. The
four dividers and their elbows SHALL be retained in both tiers.

Below the minimum box width at which even the glyph-only tier leaves the name cell
a positive width, authoring rows SHALL be omitted entirely rather than rendered
over-wide or truncated into the border.

#### Scenario: Labels shed, dividers retained

- **WHEN** the box is narrow enough that the name cell would fall below 15 columns
- **THEN** the stage cells render as four bare glyphs
- **AND** four `┊` dividers with matching `┬`/`┴` elbows are still present

#### Scenario: Row omitted at degenerate widths

- **WHEN** the box width is below the authoring row's minimum
- **THEN** no authoring row is emitted, and the openspec box's remaining rows and
  borders render exactly as they would with no authoring changes

### Requirement: Wide-layout-only, above the task bars

Authoring rows SHALL render only in the wide layout, matching the existing
openspec section, and SHALL NOT appear in the narrow or medium layouts. Within
the openspec box they SHALL be emitted as one contiguous group **above** the
task-progress bars, under the existing `specs` section caption. The openspec box
SHALL be emitted when there is at least one authoring row even if there are no
task bars, and a separator SHALL divide the authoring group from the task bars
when both are present.

#### Scenario: Not rendered in narrow or medium

- **WHEN** the statusline renders in the narrow or medium layout with authoring
  changes present
- **THEN** no authoring row appears

#### Scenario: Authoring rows precede task bars

- **WHEN** both authoring changes and changes with task bars are present in a wide render
- **THEN** the openspec box contains the authoring rows first, then a separator,
  then the task bars

#### Scenario: Section renders with authoring rows alone

- **WHEN** only authoring changes are present and no change has a `tasks.md`
- **THEN** the openspec section separator, its `specs` caption, and the authoring
  rows are rendered
