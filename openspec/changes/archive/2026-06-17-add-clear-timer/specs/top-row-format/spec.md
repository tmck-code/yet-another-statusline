## MODIFIED Requirements

### Requirement: Session timer format and fixed-width reservation

The session timer SHALL be formatted as `MM:SS` when the elapsed time is under one hour (no leading hours digit or `0:` prefix, e.g. `13:27`), and as `H:MM:SS` or `HH:MM:SS` when one or more hours have elapsed. `_fmt_elapsed_clock` SHALL continue to return the empty string for zero or negative durations. The wide layout's `elapsed_section` SHALL right-justify the formatted session timer into a fixed field of 8 visible columns (the `HH:MM:SS` worst case) so that the timer's divider column does not shift as the clock crosses `MM:SS` → `H:MM:SS` → `HH:MM:SS`. When the session has never been cleared (no `/clear` marker in the current transcript), the elapsed cell SHALL render only this session timer, byte-identical to the single-timer behaviour prior to this change.

#### Scenario: Under an hour drops the hours digit

- **WHEN** the session has run for 13 minutes 27 seconds
- **THEN** the timer string is `13:27` (no `0:` prefix)

#### Scenario: An hour or more keeps the hours digit

- **WHEN** the session has run for 1 hour 13 minutes 27 seconds
- **THEN** the timer string is `1:13:27`

#### Scenario: Column stays put as the clock grows

- **WHEN** the timer renders first as `13:27` and later as `1:13:27` at the same width
- **THEN** the timer occupies the same 8-column field (right-justified) and the timer divider column is unchanged

#### Scenario: Fresh session renders the session timer unchanged

- **WHEN** the wide layout renders and the current transcript has no `/clear` marker
- **THEN** the elapsed cell shows only the session timer, with no clear-timer glyph, identical to the pre-change rendering

## ADDED Requirements

### Requirement: Since-clear timer in the wide elapsed cell

When the current transcript has been cleared (a `/clear` marker epoch is available), the wide layout's elapsed cell SHALL show a second "since last `/clear`" timer in addition to the session timer. The clear timer SHALL be computed wall-clock as `now − clear_epoch`, clamped to a minimum of 0 for clock skew, and formatted with the same `_fmt_elapsed_clock` (`MM:SS` / `H:MM:SS`) convention as the session timer. The clear timer SHALL be rendered first (leftmost) within the cell, led by a distinguishing Nerd Font glyph and an accent colour distinct from the grey session timer; the session timer SHALL follow in its existing grey. The clear timer and session timer SHALL share the single existing elapsed-cell divider/elbow — no additional border divider is introduced.

#### Scenario: Cleared session shows both timers, clear first

- **WHEN** the wide layout renders, the transcript was cleared, and both timers fit the available width
- **THEN** the elapsed cell shows the glyphed accent clear timer leftmost followed by the grey session timer, both inside one vsep-delimited cell with a single divider

#### Scenario: Clear timer is wall-clock from the marker

- **WHEN** the most recent `/clear` occurred 18 minutes 33 seconds ago
- **THEN** the clear timer reads `18:33`

### Requirement: Elapsed-cell degradation ladder

The wide elapsed cell SHALL degrade under width pressure in a fixed order. Path protection SHALL remain the outermost guard: the entire elapsed cell SHALL still shed (render nothing) whenever including it would leave the path fewer than 5 visible columns, exactly as before this change. Within the elapsed cell's own budget, when both timers cannot fit, the layout SHALL prefer the clear timer alone over the session timer — dropping the session timer first. The resulting tiers, widest to narrowest, SHALL be: both timers → clear timer only → cell shed entirely.

#### Scenario: Both timers do not fit, clear timer wins

- **WHEN** the elapsed cell can fit one timer but not both while still protecting the path
- **THEN** only the glyphed clear timer renders and the session timer is dropped

#### Scenario: Path protection drops the whole cell

- **WHEN** including even the clear-timer-only cell would leave the path fewer than 5 visible columns
- **THEN** the entire elapsed cell sheds and neither timer renders

#### Scenario: Ample width shows both

- **WHEN** the width comfortably fits both timers and the path
- **THEN** both the clear timer and the session timer render
