# side-by-side-sections Specification

## Purpose

Define how the wide layout composes the task checklist and subagent cohort as adjacent columns within a single bordered block: the trigger conditions, the content-driven column split with a stacked fallback, the divider and elbow threading that connects the columns to the box top and bottom, height reconciliation between the two columns, and the builder-driven content width that the section renderers consume.

## Requirements

### Requirement: Side-by-side trigger

In the **wide** layout only, when the task checklist is visible AND at least one subagent is visible, the renderer SHALL attempt to compose the two sections as adjacent columns within a single bordered block rather than stacking them as two full-width sections. In the **medium** and **narrow** layouts the two sections SHALL continue to stack full-width. When only one of the two sections is present, that section SHALL render full-width exactly as before this change.

#### Scenario: Both sections present in a wide layout

- **WHEN** a wide layout is built, the checklist is visible, and at least one subagent is visible
- **THEN** the checklist and subagent cohort are composed as side-by-side columns in one block (subject to the width fallback below)

#### Scenario: Only one section present

- **WHEN** a wide layout is built and exactly one of the checklist or subagent cohort is present
- **THEN** that section renders full-width and stacked exactly as before this change

#### Scenario: Medium and narrow always stack

- **WHEN** a medium or narrow layout is built with both sections present
- **THEN** the sections stack full-width and the side-by-side composition is not used

### Requirement: Content-driven column split with fallback

The left column SHALL render the task checklist and the right column SHALL render the subagent cohort. The left column width SHALL be the smaller of the widest task line and 45% of the inner content width. The right column SHALL receive the remaining inner width after subtracting the left column and the divider. If the resulting right column would be narrower than 40 visible columns, the renderer SHALL abandon the side-by-side composition and stack the two sections full-width.

#### Scenario: Short task list yields a narrow left column

- **WHEN** the widest task line is narrower than 45% of the inner width
- **THEN** the left column is sized to the widest task line and the right column receives the rest

#### Scenario: Long task list is capped

- **WHEN** the widest task line exceeds 45% of the inner width
- **THEN** the left column is capped at 45% of the inner width and task subjects truncate to fit

#### Scenario: Insufficient remaining width falls back to stacked

- **WHEN** the computed right column would be narrower than 40 visible columns
- **THEN** the side-by-side composition is abandoned and both sections render full-width and stacked

### Requirement: Column divider and elbow threading

The two columns SHALL be separated by a single vertical `│` drawn in the border gradient at a fixed divider column, padded by one space on each side. Every combined content row SHALL carry the divider at the same column. The separator above the block SHALL grow a `┬` at the divider column and the separator (or bottom border) below the block SHALL grow a matching `┴`, so the divider connects to the box top and bottom. To support a `┬` on the heavy static→dynamic seam, `border_separator` SHALL accept downward elbow columns.

#### Scenario: Divider is continuous top to bottom

- **WHEN** a side-by-side block is rendered
- **THEN** a `┬` appears on the separator above at the divider column, a `│` appears in every combined row at that column, and a `┴` appears on the separator (or bottom border) below at that column

#### Scenario: Divider colour follows the border gradient

- **WHEN** the divider is drawn at its column
- **THEN** its colour is taken from the border gradient at that column, consistent with other vertical seams

### Requirement: Height reconciliation

The two columns SHALL be rendered independently to their own content widths, then combined row-by-row up to the height of the taller column. The shorter column SHALL be padded with blank lines of its own column width, top-aligned, so the divider and the right edge remain straight and every combined row spans the full inner width.

#### Scenario: Subagent column taller than task column

- **WHEN** the subagent column produces more lines than the task column
- **THEN** the task column is padded with blank lines at the bottom and the divider runs straight through the padded rows

#### Scenario: Task column taller than subagent column

- **WHEN** the task column produces more lines than the subagent column
- **THEN** the subagent column is padded with blank lines at the bottom and every combined row spans the full inner width

### Requirement: Builder-driven content width

`Renderer.task_row` and `Renderer.subagent_row` SHALL render into an explicit content width supplied by the layout builder rather than deriving width from the terminal width. The subagent two-line versus one-line form SHALL be selected by a builder-supplied flag rather than an internal terminal-width threshold, so a narrow side-by-side column can still use the two-line form.

#### Scenario: Section renderers honour the supplied width

- **WHEN** a layout builder calls `task_row` or `subagent_row` with a content width
- **THEN** the produced lines fit within that width as measured by the visible-width helper

#### Scenario: Two-line form forced in a narrow column

- **WHEN** the builder composes a side-by-side block and requests the subagent two-line form for a narrow column
- **THEN** the subagent rows render in two-line form regardless of the column width
