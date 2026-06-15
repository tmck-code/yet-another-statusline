## ADDED Requirements

### Requirement: Two-column agent layout at wide terminal widths
When `per_agent` is True and the terminal width is ≥ 160, workflow agents SHALL be rendered in pairs side-by-side within a single content row, separated by a `  │  ` vertical divider. Each half SHALL receive `(inner - 5) // 2` columns where `inner = width - 4`. Agents SHALL be paired sequentially by `first_timestamp` order. When the agent count is odd, the final agent SHALL be rendered full-width. Done and running agents MAY be mixed within a pair. When terminal width is < 160, agents SHALL render one per row as before.

#### Scenario: Agents paired at width ≥ 160
- **WHEN** `per_agent` is True, width ≥ 160, and there are 4 agents
- **THEN** the layout emits 2 content rows, each containing 2 agents separated by `  │  `

#### Scenario: Odd agent rendered full-width
- **WHEN** `per_agent` is True, width ≥ 160, and there are 3 agents
- **THEN** the layout emits 2 content rows: one with agents 1+2 paired, one with agent 3 full-width

#### Scenario: Below threshold renders one per row
- **WHEN** `per_agent` is True and width < 160
- **THEN** each agent occupies its own content row (existing behaviour)

#### Scenario: Done and running agents may be paired together
- **WHEN** width ≥ 160 and agents 1 (done) and 2 (running) are adjacent in timestamp order
- **THEN** they appear side-by-side in the same row; agent 1 renders with dim done styling

### Requirement: Two-column mode uses one-line agent form
In two-column layout, each agent SHALL be rendered using the one-line (non-twoline) form regardless of terminal width. The `twoline=True` path SHALL only apply in single-column layout.

#### Scenario: One-line form used in two-column mode
- **WHEN** width ≥ 160 and agents are rendered in two-column mode
- **THEN** each agent is rendered with `twoline=False` (single-line form)
