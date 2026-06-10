# path-display Specification

## Purpose

Define the cwd/branch section's width-degradation behavior: the cwd path is treated as a whole unit (included in full or omitted entirely, never middle-ellipsized), the fields are shed in a fixed priority order with the branch surviving longer than the path, and the terminal glyph-only state is overflow-safe.

## Requirements

### Requirement: Whole-unit cwd include or omit

The cwd path SHALL be rendered as a whole unit: it is either included in full
(using the existing initial-collapsed `short_pwd` form) or omitted entirely. The
system SHALL NOT apply middle-ellipsis or any partial truncation to the cwd path
at any width.

#### Scenario: Path included when it fits

- **WHEN** the available width fits the path-plus-branch line
- **THEN** the full `short_pwd` is shown alongside the branch

#### Scenario: Path omitted whole when it does not fit

- **WHEN** the available width cannot fit the path-plus-branch line but can fit
  the branch alone
- **THEN** the cwd path is dropped entirely and the branch is retained, with no
  ellipsized path fragment shown

### Requirement: Degradation priority and terminal state

Under decreasing width the section SHALL shed fields in this order: commit, then
dirty markers, then the cwd path (whole), then the branch. The branch SHALL be
retained for longer than the cwd path. When even the branch does not fit, the
section SHALL fall back to a presence glyph only. This terminal state SHALL be
overflow-safe — it SHALL NOT exceed the available width or disturb the box
border alignment.

#### Scenario: Branch outlives the path

- **WHEN** width shrinks past the point where path-plus-branch fits
- **THEN** the path is dropped before the branch

#### Scenario: Glyph-only terminal state

- **WHEN** the available width cannot fit even the branch alone
- **THEN** only the presence glyph is shown and the rendered width stays within
  the available width

#### Scenario: No partial path or partial-branch ellipsis in the path ladder

- **WHEN** the section degrades at any width
- **THEN** neither the cwd path nor the branch is rendered with a middle-ellipsis
  fragment; each is shown in full or omitted as a whole
