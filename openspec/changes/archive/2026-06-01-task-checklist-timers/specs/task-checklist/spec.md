## ADDED Requirements

### Requirement: Plan Generation scoping

The task parser SHALL render and count only the **latest plan generation**, not every task created in the session. A new generation SHALL begin when a `TaskCreate` event is folded while **all** currently-known tasks are `completed`; that event discards the prior generation and restarts task ids at `#1`. A `TaskCreate` folded while any task is still `pending` or `in_progress` SHALL append to the current generation. The resulting `done/total` count SHALL reflect only the latest generation.

#### Scenario: New batch after completion starts a fresh generation
- **WHEN** every task in the list is `completed` and a later `TaskCreate` is folded
- **THEN** the prior tasks are dropped and the new task is `#1` of a fresh generation

#### Scenario: Create while work is open appends to the current generation
- **WHEN** a `TaskCreate` is folded while at least one task is still `pending` or `in_progress`
- **THEN** the new task is appended to the current generation, keeping the existing tasks

#### Scenario: Count reflects only the latest generation
- **WHEN** earlier completed generations exist before the current one
- **THEN** `done/total` counts only the tasks of the latest generation

### Requirement: Per-task timing

A **Task** SHALL carry `started_at` and `completed_at` (epoch seconds, or absent). On a `TaskUpdate` transitioning a task **to** `in_progress`, the parser SHALL set `started_at` to that event's timestamp and clear `completed_at`. On a `TaskUpdate` transitioning a task **to** `completed`, it SHALL set `completed_at`. A task's **Task Timer** SHALL read the live elapsed `now − started_at` while `in_progress`, the frozen duration `completed_at − started_at` while `completed`, and SHALL be absent for a `pending` task or any task that was never `in_progress`.

#### Scenario: Timer starts when work begins
- **WHEN** a task transitions to `in_progress`
- **THEN** its `started_at` is the timestamp of that transition and its Task Timer counts up live from then

#### Scenario: Timer freezes on completion
- **WHEN** a task that was `in_progress` transitions to `completed`
- **THEN** its Task Timer shows the frozen duration `completed_at − started_at` and no longer advances

#### Scenario: Reopened task restarts its timer
- **WHEN** a `completed` task transitions back to `in_progress`
- **THEN** `started_at` is overwritten with the new timestamp, `completed_at` is cleared, and the live timer counts from the new start

#### Scenario: Task that never started shows no duration
- **WHEN** a task goes `pending → completed` with no intervening `in_progress`
- **THEN** it has no `started_at` and renders no Task Timer

### Requirement: Total Elapsed

The checklist header SHALL show a **Total Elapsed** wall-clock span for the current generation: from the earliest task `started_at` to `now` while any task is `in_progress`, or to the latest `completed_at` once nothing is in progress. When no task in the generation has ever started, Total Elapsed SHALL be absent.

#### Scenario: Total runs live while work is active
- **WHEN** any task in the generation is `in_progress`
- **THEN** Total Elapsed spans the earliest `started_at` to `now` and advances each render

#### Scenario: Total freezes when the plan is done
- **WHEN** no task is `in_progress`
- **THEN** Total Elapsed spans the earliest `started_at` to the latest `completed_at`

### Requirement: Active Window

When rendered as a full list, the checklist SHALL show an **Active Window**: an active-anchored slice of at most **6 content rows, inclusive of any `+N done` / `+N more` collapse lines**. The window SHALL keep the `in_progress` item visible and bias toward upcoming `pending` items. Completed items above the window SHALL collapse into a `+N done` line and pending items below into a `+N more` line, each counting against the 6-row budget. With no `in_progress` task the window SHALL start at the first pending items; with all tasks completed it SHALL show the most recent completed items.

#### Scenario: Long plan stays within the row budget
- **WHEN** the generation has more tasks than fit the budget
- **THEN** the rendered task rows (items plus any collapse lines) total at most 6, and the `in_progress` item is among them

#### Scenario: Clipped completed and pending collapse into affordances
- **WHEN** completed items fall above the window or pending items below it
- **THEN** a `+N done` line and/or a `+N more` line represents the hidden counts, within the budget

### Requirement: Pinned visibility while active

The checklist SHALL remain visible while any task is `in_progress`, regardless of the freshness cap, so a long-running step's live timer is never hidden. When no task is `in_progress`, the existing freshness behaviour SHALL apply: hidden after the 120s cap since the last task event, with a 20s grace once all tasks are `completed`.

#### Scenario: Long step keeps the list visible
- **WHEN** a task has been `in_progress` longer than the freshness cap with no new task event
- **THEN** the checklist stays visible and its live timer keeps counting

#### Scenario: Finished plan still fades out
- **WHEN** all tasks are `completed` and the grace period elapses
- **THEN** the checklist is hidden

### Requirement: Layout-specific rendering

The checklist SHALL render the full header + Active Window in the **wide** and **medium** layouts. In the **narrow** layout it SHALL render a single compact line — the checklist glyph, `done/total`, and the active task's live timer when a task is `in_progress` — and no subject text. Each full-list item row SHALL show a state glyph (distinct constants for `pending`, `in_progress`, `completed`), the task subject truncated to fit, and a right-aligned Task Timer column; completed durations render dim, the in_progress live timer renders bright, pending rows show no timer. All column widths SHALL be measured with the visible-width helper, never `len()`.

#### Scenario: Wide and medium show the full checklist
- **WHEN** a wide or medium layout is built and the checklist is visible
- **THEN** it renders the header (glyph + done/total + Total Elapsed) followed by the Active Window of item rows

#### Scenario: Narrow shows the compact line
- **WHEN** a narrow layout is built and the checklist is visible
- **THEN** it renders one line of glyph + done/total + the active task's live timer (omitted if nothing is in_progress), with no per-item rows

#### Scenario: Timers align in a trailing column
- **WHEN** multiple item rows carry timers
- **THEN** the timer values right-align in a fixed trailing column and subjects truncate with an ellipsis before that column

### Requirement: Timer formatting

A duration SHALL be formatted as `m:ss` (for example `0:07`, `12:04`) and SHALL roll over to `h:mm:ss` once it reaches one hour. The same formatting SHALL apply to per-task Task Timers and to Total Elapsed.

#### Scenario: Sub-hour durations use m:ss
- **WHEN** a duration is under one hour
- **THEN** it renders as `m:ss` with a zero-padded seconds field

#### Scenario: Durations of an hour or more use h:mm:ss
- **WHEN** a duration is one hour or more
- **THEN** it renders as `h:mm:ss` with zero-padded minutes and seconds
