## ADDED Requirements

### Requirement: Single-line tokens/cost/rate row

The wide layout's tokens/cost row (`Renderer.tokens_cost`) SHALL render as exactly
**one** content line, not two. The line SHALL retain three columns in order —
tokens, then cost, then rate-and-sparkline — separated by the standard gradient
`│` vertical dividers. `tokens_cost` SHALL return a single-element list of content
lines together with the divider columns so the builder can thread one set of
matching `┬`/`┴` elbows onto the separators above and below the row. The previous
60s sparkline tick marker (`spark_mark_col`) SHALL be removed, since a midpoint
marker has no referent once the whole bar spans 60s.

#### Scenario: Row occupies one content line

- **WHEN** the wide layout renders the tokens/cost row
- **THEN** `tokens_cost` returns exactly one content line
- **AND** every `│` in that line has a matching `┬` on the separator above and `┴`
  on the separator below at the same visual column

#### Scenario: Three columns preserved in order

- **WHEN** the single-line row is rendered with day stats enabled
- **THEN** the content reads tokens, then cost, then rate-and-sparkline, left to
  right, divided by the gradient `│` separators

### Requirement: Session/day slash-merged figures

With day stats enabled, the tokens column SHALL merge each session figure with its
day counterpart as `session/day`: input as `↓ <sess_in>/<day_in>`, the paired
cache read in parentheses as `(<sess_cache>/<day_cache>)`, and output as
`↑ <sess_out>/<day_out>`. The cost column SHALL render `$<sess_cost> / $<day_cost>`.
All token counts SHALL be formatted with the existing `fmt_tok` abbreviation
(e.g. `128.4K`, `1.9M`).

#### Scenario: Merged tokens and cost

- **WHEN** session totals are in=128.4K, cache=1.2M, out=47.3K and day totals are
  in=1.9M, cache=18.3M, out=612.5K, session cost $3.27 and day cost $41.88
- **THEN** the tokens column reads `↓ 128.4K/1.9M (1.2M/18.3M) ↑ 47.3K/612.5K`
- **AND** the cost column reads `$3.27 / $41.88`

### Requirement: Single-row block-element sparkline over a 60s window

The token-rate sparkline SHALL be drawn on a single row using the block-element
glyphs ` ▁▂▃▄▅▆▇█` (U+2581–U+2588, plus a blank for zero), with each cell's glyph
chosen by its value's ratio to the window peak and coloured by that same ratio as
today (the most recent cell dimmed when live). The sparkline SHALL read the last
`TokenRate.WINDOW` seconds of history (the resolved `token_window`, default 60s),
not `TokenRate.WINDOW * 2`. The two-row half-block sparkline built from the
`SPARK_RISE_*` / `SPARK_FALL_*` "Symbols for Legacy Computing" glyphs SHALL be
removed.

#### Scenario: Sparkline is one row of block elements

- **WHEN** the rate sparkline is rendered for a non-empty history
- **THEN** it is a single row of glyphs drawn only from the set ` ▁▂▃▄▅▆▇█`
- **AND** no glyph in the U+1FBxx "Symbols for Legacy Computing" range appears

#### Scenario: Window is 60s

- **WHEN** the resolved `token_window` is 60
- **THEN** the sparkline history spans 60 seconds of buckets, not 120

### Requirement: Day-stats-disabled session-only row

When `show_day_stats` resolves to false, the tokens/cost row SHALL drop every day
figure and render session-only: tokens `↓ <sess_in> (<sess_cache>) ↑ <sess_out>`,
cost `$<sess_cost>`, with the rate-and-sparkline column unchanged. The row SHALL
remain a single content line with the same three-column elbow structure.

#### Scenario: Session-only content

- **WHEN** `show_day_stats` is false and session totals are in=128.4K, cache=1.2M,
  out=47.3K, session cost $3.27
- **THEN** the tokens column reads `↓ 128.4K (1.2M) ↑ 47.3K`
- **AND** the cost column reads `$3.27`
- **AND** no day token count or day cost appears anywhere in the row

#### Scenario: Default keeps day stats

- **WHEN** no `YAS_SHOW_DAY_STATS` env var and no `[tokens].show_day_stats` toml
  value are set
- **THEN** day stats are shown (the merged `session/day` form is used)
