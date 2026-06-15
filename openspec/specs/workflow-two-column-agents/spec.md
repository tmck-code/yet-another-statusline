# workflow-two-column-agents Specification

## Purpose

Define the two-column agent layout for workflow runs at wide terminal widths: when `per_agent` rendering is active and the terminal is at least 120 columns wide (the TWO_COL_WF_WIDTH threshold), workflow agents are paired side-by-side within a single content row to halve vertical space usage. Each agent in two-column mode uses the one-line form. Below the threshold, agents render one per row as before.

## Requirements

### Requirement: Two-column agent layout at wide terminal widths

When `per_agent` is True and the terminal width is ≥ 120, workflow agents SHALL be rendered in pairs side-by-side within a single content row, separated by a `  │  ` vertical divider. Each half SHALL receive `(inner - 5) // 2` columns where `inner = width - 4`. Agents SHALL be paired sequentially by `first_timestamp` order. When the agent count is odd, the final agent SHALL be rendered in the left column only, with a blank right half, so it stays inside the L/R section and the column divider remains unbroken. Done and running agents MAY be mixed within a pair. When terminal width is < 120, agents SHALL render one per row as before.

#### Scenario: Agents paired at width ≥ 120

- **WHEN** `per_agent` is True, width ≥ 120, and there are 4 agents
- **THEN** the layout emits 2 content rows, each containing 2 agents separated by `  │  `

#### Scenario: Odd agent rendered in the left column

- **WHEN** `per_agent` is True, width ≥ 120, and there are 3 agents
- **THEN** the layout emits 2 content rows: one with agents 1+2 paired, one with agent 3 in the left column and a blank right half, both carrying the divider

#### Scenario: Below threshold renders one per row

- **WHEN** `per_agent` is True and width < 120
- **THEN** each agent occupies its own content row (existing behaviour)

### Requirement: Column divider spans the whole run block and joins the box

In two-column mode the column divider `│` SHALL be embedded in every row of a run block — the header, every paired/odd agent row, the summary, and any `+N more workflows` overflow row — at the shared column `workflow_divider_col(width)`, so the bar runs unbroken from the header down to the summary. The block SHALL carry no internal separator rows. `build_wide` SHALL thread the matching `┬` onto the separator above the first header and carry the matching `┴` down to the border (or separator) below the last summary, so the bar joins the box at both ends rather than floating.

#### Scenario: Divider runs through header and summary

- **WHEN** `per_agent` is True, width ≥ 120, and a run is rendered
- **THEN** the header row and the summary row each contain the divider `│` at `workflow_divider_col(width)`, and no `separator_dim` rows appear between the header and summary

#### Scenario: Divider joins the box at top and bottom

- **WHEN** `build_wide` renders a two-column workflow block
- **THEN** the separator above the header carries a `┬` and the border/separator below the summary carries a `┴`, both at the divider column

#### Scenario: Done and running agents may be paired together

- **WHEN** width ≥ 120 and agents 1 (done) and 2 (running) are adjacent in timestamp order
- **THEN** they appear side-by-side in the same row; agent 1 renders with dim done styling

### Requirement: Two-column mode uses one-line agent form

In two-column layout, each agent SHALL be rendered using the one-line (non-twoline) form regardless of terminal width. The `twoline=True` path SHALL only apply in single-column layout.

#### Scenario: One-line form used in two-column mode

- **WHEN** width ≥ 120 and agents are rendered in two-column mode
- **THEN** each agent is rendered with `twoline=False` (single-line form)
