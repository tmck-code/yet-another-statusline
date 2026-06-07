## MODIFIED Requirements

### Requirement: Layout-specific rendering

The checklist SHALL render the full header + Active Window in the **wide** and **medium** layouts. In the **narrow** layout it SHALL render a single compact line — the checklist glyph, `done/total`, and the active task's live timer when a task is `in_progress` — and no subject text. Each full-list item row SHALL show a state glyph (distinct constants for `pending`, `in_progress`, `completed`), the task subject truncated to fit, and a right-aligned Task Timer column; completed durations render dim, the in_progress live timer renders bright, pending rows show no timer. All column widths SHALL be measured with the visible-width helper, never `len()`. The wide checklist SHALL render into a content width supplied by the layout builder, and MAY appear as the left column of a side-by-side section when a subagent cohort is also present; in that case it renders into the narrower left-column width using the same header + Active Window structure.

#### Scenario: Wide and medium show the full checklist

- **WHEN** a wide or medium layout is built and the checklist is visible
- **THEN** it renders the header (glyph + done/total + Total Elapsed) followed by the Active Window of item rows

#### Scenario: Narrow shows the compact line

- **WHEN** a narrow layout is built and the checklist is visible
- **THEN** it renders one line of glyph + done/total + the active task's live timer (omitted if nothing is in_progress), with no per-item rows

#### Scenario: Timers align in a trailing column

- **WHEN** multiple item rows carry timers
- **THEN** the timer values right-align in a fixed trailing column and subjects truncate with an ellipsis before that column

#### Scenario: Checklist renders into a side-by-side left column

- **WHEN** a wide layout composes a side-by-side section and the checklist is the left column
- **THEN** the checklist renders its header + Active Window into the supplied left-column width, with subjects truncating to fit that width
