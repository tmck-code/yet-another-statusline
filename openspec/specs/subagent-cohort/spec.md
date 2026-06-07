# subagent-cohort Specification

## Purpose

Define how the statusline detects subagent completion, scopes the visible cohort to the current turn, retires the section as a unit after a grace window, sweeps dirty cohorts after silence, and renders finished agents with a distinct visual treatment.

## Requirements

### Requirement: Done detection via end_turn

The statusline SHALL treat a subagent as **Done** when, and only when, its transcript jsonl contains an assistant message whose `message.stop_reason` equals `"end_turn"`. The timestamp of that line SHALL be captured as the subagent's `end_ts`. Transcript-write staleness SHALL NOT, on its own, mark a subagent Done.

#### Scenario: Clean finish marks Done

- **WHEN** a subagent transcript's final assistant message carries `stop_reason: "end_turn"`
- **THEN** the subagent is Done and its `end_ts` is the timestamp of that line

#### Scenario: Silence does not mark Done

- **WHEN** a subagent transcript has had no writes for longer than the liveness window but contains no `end_turn`
- **THEN** the subagent is NOT marked Done (it is handled by the janitor sweep instead)

#### Scenario: Interrupted agent never emits end_turn

- **WHEN** a subagent was interrupted, killed, or errored and its transcript ends without `stop_reason: "end_turn"`
- **THEN** the subagent is never marked Done and never receives the Done visual treatment

### Requirement: Turn-scoped cohort membership

The statusline SHALL scope the visible subagent cohort to the current turn. A subagent is a member of the cohort when its `first_timestamp` is at or after the last user-prompt timestamp for the session, OR when it is still actively writing (its transcript was written within the liveness window) regardless of when it started. A running subagent SHALL always be shown regardless of age; the age cutoff applies only to finished or idle subagents.

#### Scenario: Agent spawned this turn is in the cohort

- **WHEN** a subagent's `first_timestamp` is at or after the last user-prompt timestamp
- **THEN** it is a member of the cohort

#### Scenario: Pre-turn straggler still writing is kept

- **WHEN** a subagent started before the last user prompt but its transcript was written within the liveness window
- **THEN** it remains a member of the cohort until it finishes or dies

#### Scenario: Running agent is always shown

- **WHEN** a subagent is still running (not Done and written within the liveness window)
- **THEN** it is shown regardless of how long ago it started

#### Scenario: Old finished agent from a prior turn is excluded

- **WHEN** a subagent finished in a previous turn and its `first_timestamp` is before the last user-prompt timestamp
- **THEN** it is not shown in the current turn's cohort

### Requirement: Cohort-level retirement with grace window

The statusline SHALL keep every cohort member visible until the **last** member is Done, then retire the entire section together after a grace window of 20 seconds measured from the most recent member's `end_ts`. Members that finished earlier SHALL remain visible (dimmed) until the whole section retires.

#### Scenario: Section persists while any member runs

- **WHEN** at least one cohort member is not yet Done
- **THEN** the whole section, including already-finished members, remains visible

#### Scenario: Whole section retires after grace

- **WHEN** every cohort member is Done and 20 seconds have elapsed since the most recent member's `end_ts`
- **THEN** the entire subagent section is removed

#### Scenario: Finished member waits for stragglers

- **WHEN** member A is Done but sibling member B is still running
- **THEN** member A stays on screen (dimmed) rather than dropping off individually

### Requirement: Janitor sweep for dirty cohorts

When a cohort contains at least one member that is not Done and has stopped writing (so the clean grace countdown can never arm), the statusline SHALL remove the entire section after 60 seconds of total silence across all of the cohort's transcripts.

#### Scenario: Dirty cohort swept after silence

- **WHEN** a cohort contains a member that never emitted `end_turn` and no member's transcript has been written for 60 seconds
- **THEN** the entire section is removed

#### Scenario: Janitor does not fire while a member writes

- **WHEN** any cohort member's transcript was written within the last 60 seconds
- **THEN** the janitor does not sweep the section

### Requirement: Finished-agent visual treatment

A Done subagent's row SHALL be visually distinguished from a running one by dimming and a frozen timer, not by a leading marker glyph. The running/Done distinction SHALL NOT use the `▶`/`✓` markers — the elapsed duration now occupies that leading position. A Done row SHALL be dimmed (overriding the running row's rainbow marker and field colours) and its elapsed field SHALL be frozen at `end_ts − first_timestamp` rather than continuing to tick from the current time. A running row SHALL render with live colours and a live-ticking elapsed field.

#### Scenario: Done row shows dimmed styling and a frozen timer

- **WHEN** a subagent is Done and still within the cohort grace window
- **THEN** its row renders with dimmed colours and a frozen elapsed duration, with no `▶`/`✓` marker

#### Scenario: Elapsed freezes at completion

- **WHEN** a subagent is Done
- **THEN** its elapsed field shows `end_ts − first_timestamp` and does not increase on subsequent renders

#### Scenario: Running row uses live colours and a ticking timer

- **WHEN** a subagent is still running
- **THEN** its row renders with live colours and a live-ticking elapsed field, with no `▶`/`✓` marker

### Requirement: Graceful fallback without a prompt marker

When the last user-prompt timestamp is unavailable (the marker file is missing, unreadable, stale, or its session entry is absent), the statusline SHALL scope the cohort by a recency window of 60 seconds instead of by turn, and SHALL render without error.

#### Scenario: Missing marker degrades to recency window

- **WHEN** no usable last-prompt timestamp exists for the session
- **THEN** the cohort comprises subagents active or finished within the last 60 seconds, and rendering proceeds normally

#### Scenario: Unreadable marker never breaks rendering

- **WHEN** the marker file is truncated or contains invalid JSON
- **THEN** the statusline falls back to the recency window and does not raise
