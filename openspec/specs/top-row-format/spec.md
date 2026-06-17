# top-row-format Specification

## Purpose
TBD - created by archiving change restyle-top-row. Update Purpose after archive.
## Requirements
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

### Requirement: Rate-limit segment icons and separator

In the wide layout the 5-hour rate-limit segment SHALL lead with the timer-outline icon `ICON_LIMIT_5H` (nf-md-timer_outline, U+F051B) and the 7-day segment SHALL lead with the calendar-week icon `ICON_LIMIT_7D` (nf-md-calendar_week_begin, U+F0A34), replacing the previous shared helper glyph. When both segments are present, they SHALL be separated by a dotted vertical divider ` ┆ ` (`SEP_RATE`, U+2506) rather than ` | `.

#### Scenario: Both segments render with their icons and dotted separator

- **WHEN** a wide render has both a 5-hour and a 7-day rate-limit value
- **THEN** the 5-hour segment is preceded by the timer-outline icon, the 7-day segment by the calendar-week icon, and the two are joined by ` ┆ `

#### Scenario: Seven-day segment absent

- **WHEN** the 7-day rate limit has no usage and no reset
- **THEN** only the 5-hour segment (with its timer-outline icon) renders and no ` ┆ ` separator appears

### Requirement: Reset-countdown placement and format

The 5-hour reset countdown SHALL be positioned at the front of the 5-hour segment, immediately after its icon and ahead of the usage and trend percentages, formatted as `(-H:MM)` — parenthesised, leading minus, hours kept, seconds dropped (e.g. `(-2:00)`, `(-0:45)`). When the limit has no reset (infinite/unknown), the existing infinite indicator SHALL render and no countdown SHALL appear.

#### Scenario: Countdown leads the segment

- **WHEN** the 5-hour limit resets in 2 hours exactly with 30.0% used
- **THEN** the segment renders the timer icon, then `(-2:00)`, then `30.0%`, then the trend

#### Scenario: Under an hour keeps the single-digit hour

- **WHEN** the 5-hour limit resets in 45 minutes
- **THEN** the countdown renders as `(-0:45)`

### Requirement: One-decimal percentages

All rate-limit usage percentages and burndown trend percentages SHALL render at exactly one decimal place (e.g. `30.0%`, `-30.1%`) in both the wide and the compact layouts. `burndown_trend` SHALL format its delta to one decimal place.

#### Scenario: Usage and trend both at one decimal

- **WHEN** a usage percentage is 30 and a trend delta is -30.14
- **THEN** they render as `30.0%` and `-30.1%` respectively

#### Scenario: Compact layout matches

- **WHEN** a compact (narrow or medium) layout renders a usage percentage
- **THEN** it renders at one decimal place

### Requirement: Model pill single glyph and parenthesised effort

The model pill SHALL lead with a single glyph `GLYPH_MODEL_LIGHT` (nf-md-lightbulb_on_40, U+F1A51), replacing both the previous monitor and brain glyphs, with one extra space of padding between the pill's left edge and the glyph. In fast mode the lead glyph SHALL be swapped to `GLYPH_BURN_FAST`. The effort/thinking value SHALL be rendered as parenthesised text (e.g. `(medium)`) following the model name, and SHALL be omitted entirely — including the parentheses — when the effort/thinking value is empty. The compact model pills SHALL use the same `GLYPH_MODEL_LIGHT` lead glyph for cross-width consistency.

#### Scenario: Wide pill with effort

- **WHEN** a wide render shows model `Sonnet 4.6` with effort `medium`
- **THEN** the pill renders the lightbulb glyph (with leading padding), the model name, then `(medium)`

#### Scenario: Empty effort omits the parentheses

- **WHEN** the model has no effort/thinking value
- **THEN** the pill renders the lightbulb glyph and model name with no trailing parentheses

#### Scenario: Fast mode swaps the lead glyph

- **WHEN** fast mode is active
- **THEN** the lead glyph is the burn glyph rather than the lightbulb

#### Scenario: Compact pills share the glyph

- **WHEN** a narrow or medium layout renders the model pill
- **THEN** its lead glyph is `GLYPH_MODEL_LIGHT`

