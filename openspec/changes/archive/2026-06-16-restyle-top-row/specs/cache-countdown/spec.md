## MODIFIED Requirements

### Requirement: Cache Countdown rendering on the wide path/model row

The wide layout SHALL render the **Cache Countdown** as its own vsep-delimited section on the path/model content row, positioned between the rate-limit helper and the model section, with a single left divider `│`; the model section (plain text or flush-right pill) SHALL remain flush to the right edge. The section SHALL display the cache glyph (`GLYPH_CACHE`, nf-oct-cache ``) followed by the remaining time formatted as `MM:SS` (zero-padded minutes and seconds, e.g. `04:29`), rolling to `H:MM:SS` when the remaining time is at or above one hour (e.g. `1:05:00`). The remaining-time figure SHALL be coloured by `fill_colour(elapsed_pct)` so it runs green when fresh and red near expiry. The new divider SHALL be threaded as an elbow column into the row's top border (`downs`) and following separator (`ups`) so the `┬`/`│`/`┴` stay aligned. Medium and narrow layouts SHALL NOT render the Cache Countdown.

#### Scenario: Section renders with glyph, value, and divider

- **WHEN** a wide render has a live `cache_countdown` of `(187, 38)`
- **THEN** the path/model row contains a `│`-delimited section showing the cache glyph and `03:07`, and that divider's column appears in the top border `downs` and the following separator `ups`

#### Scenario: Remaining time at or above an hour rolls to H:MM:SS

- **WHEN** a wide render has a live `cache_countdown` whose remaining time is `3905` seconds (1 h 5 m 5 s)
- **THEN** the section displays `1:05:05`

#### Scenario: Colour tracks elapsed percentage

- **WHEN** `elapsed_pct` crosses from the safe band into the alert band
- **THEN** the remaining-time figure's colour changes from the theme safe colour to the theme alert colour (the same ladder as the rate-limit percentages)

#### Scenario: Narrow and medium omit it

- **WHEN** the same session renders at narrow and medium widths
- **THEN** no Cache Countdown section appears in either layout
