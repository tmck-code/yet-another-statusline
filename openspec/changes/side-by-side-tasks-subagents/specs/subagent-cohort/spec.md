## MODIFIED Requirements

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
