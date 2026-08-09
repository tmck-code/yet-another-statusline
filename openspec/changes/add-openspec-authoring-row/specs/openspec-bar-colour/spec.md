## MODIFIED Requirements

### Requirement: Name-derived gradient selection

An OpenSpec **task-progress** bar SHALL select its gradient from
`SPEC_GRADIENTS` using a hash of the change name modulo the palette length, not
the change's position in the list. The same change name SHALL always map to the
same gradient, and the mapping SHALL be independent of the change's order among
the rendered bars.

This rule scopes to the task-progress bar only. The authoring-stage row SHALL NOT
use a per-name spec gradient: its dashed dividers take the frame's border
gradient at their own columns, and its stage glyphs take the renderer's
success/warning/label colours by slot state. A change therefore SHALL NOT be
expected to keep a single identifying colour across the authoring→tasks handover.

#### Scenario: Same name maps to the same gradient

- **WHEN** a task-progress bar for a change with a given name is rendered in two
  different list positions
- **THEN** it uses the same gradient in both cases

#### Scenario: Distinct names spread across the palette

- **WHEN** several differently-named changes are rendered as task-progress bars
- **THEN** their gradient selection is driven by their names rather than their
  ordinal positions

#### Scenario: Authoring row does not use a spec gradient

- **WHEN** an authoring-stage row is rendered for a change
- **THEN** no colour from `SPEC_GRADIENTS` appears in the row
- **AND** each divider's colour is the border gradient at that divider's column
