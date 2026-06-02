## ADDED Requirements

### Requirement: Prompt-cache anchor extraction from the transcript

`TranscriptUsage` SHALL capture, during its existing single forward scan of the transcript jsonl, the wall-clock `timestamp` of the most recent line whose `message.usage` shows prompt-cache activity — that is, `cache_read_input_tokens > 0` OR `cache_creation_input_tokens > 0`. It SHALL expose this as a raw `cache_anchor_epoch` (Unix seconds, `0.0` when no such line exists). The scan SHALL NOT add a second pass over the file; it SHALL retain the most-recent matching line's raw timestamp string and convert it to epoch exactly once, after the scan completes, using the existing `session` ISO-to-epoch helper.

#### Scenario: Anchor is the latest cache-bearing line

- **WHEN** a transcript contains several assistant lines with cache activity at increasing timestamps followed by a non-cache line
- **THEN** `cache_anchor_epoch` equals the epoch of the LAST cache-bearing line, not the last line overall

#### Scenario: No cache activity yields a zero anchor

- **WHEN** a transcript contains no line with `cache_read_input_tokens > 0` or `cache_creation_input_tokens > 0`
- **THEN** `cache_anchor_epoch` is `0.0`

#### Scenario: The transcript is still scanned exactly once

- **WHEN** `cache_anchor_epoch` and the token-usage totals are both read from one `TranscriptUsage`
- **THEN** the transcript file is read a single time (the anchor is captured in the same pass that sums tokens)

### Requirement: Cache TTL tier detection

`TranscriptUsage` SHALL expose a raw `cache_ttl` (seconds) taken from the same anchor line as `cache_anchor_epoch`. The TTL SHALL be `3600` when that line reports `cache_creation.ephemeral_1h_input_tokens > 0`, and `300` otherwise. When there is no anchor line, `cache_ttl` SHALL be `0`. The 300 s and 3600 s values SHALL be named constants in `constants.py` (`CACHE_TTL_SECONDS`, `CACHE_TTL_1H_SECONDS`).

#### Scenario: One-hour ephemeral tier

- **WHEN** the anchor line's usage contains `cache_creation.ephemeral_1h_input_tokens > 0`
- **THEN** `cache_ttl` is `3600`

#### Scenario: Default five-minute tier

- **WHEN** the anchor line has cache activity but no `ephemeral_1h_input_tokens`
- **THEN** `cache_ttl` is `300`

### Requirement: Cache Countdown derivation on SessionView

`SessionView` SHALL expose a lazily-evaluated, cached `cache_countdown` derived from `transcript_usage`'s raw anchor and the view's single frozen `now`. It SHALL compute `remaining = cache_ttl − (now − cache_anchor_epoch)` and `elapsed_pct = 100 − round(remaining · 100 / cache_ttl)`, returning the pair `(remaining, elapsed_pct)`. `cache_countdown` SHALL be `None` when there is no anchor (`cache_anchor_epoch == 0.0` or `cache_ttl == 0`) OR when `remaining <= 0` (expired). `cache_countdown` SHALL hold no ANSI, formatting, or render geometry.

#### Scenario: Fresh cache reports remaining time

- **WHEN** the anchor was 90 s before `now` on the 300 s tier
- **THEN** `cache_countdown` is non-`None` with `remaining == 210` and `elapsed_pct == 30`

#### Scenario: Expired cache is None

- **WHEN** the anchor was 400 s before `now` on the 300 s tier
- **THEN** `cache_countdown` is `None`

#### Scenario: No cache event is None

- **WHEN** `cache_anchor_epoch` is `0.0`
- **THEN** `cache_countdown` is `None`

#### Scenario: Derivation uses the frozen clock

- **WHEN** `cache_countdown` is read on a `SessionView` constructed with an explicit `now`
- **THEN** the remaining time is computed against that single `now`, not a fresh wall-clock read

### Requirement: Cache Countdown rendering on the wide path/model row

The wide layout SHALL render the **Cache Countdown** as its own vsep-delimited section on the path/model content row, positioned between the rate-limit helper and the model section, with a single left divider `│`; the model section (plain text or flush-right pill) SHALL remain flush to the right edge. The section SHALL display the cache glyph (`GLYPH_CACHE`, nf-oct-cache ``) followed by the remaining time formatted by `fmt_dur` (e.g. `42s`, `3m07s`, `1h05m`). The remaining-time figure SHALL be coloured by `fill_colour(elapsed_pct)` so it runs green when fresh and red near expiry. The new divider SHALL be threaded as an elbow column into the row's top border (`downs`) and following separator (`ups`) so the `┬`/`│`/`┴` stay aligned. Medium and narrow layouts SHALL NOT render the Cache Countdown.

#### Scenario: Section renders with glyph, value, and divider

- **WHEN** a wide render has a live `cache_countdown` of `(187, 38)`
- **THEN** the path/model row contains a `│`-delimited section showing the cache glyph and `3m07s`, and that divider's column appears in the top border `downs` and the following separator `ups`

#### Scenario: Colour tracks elapsed percentage

- **WHEN** `elapsed_pct` crosses from the safe band into the alert band
- **THEN** the remaining-time figure's colour changes from the theme safe colour to the theme alert colour (the same ladder as the rate-limit percentages)

#### Scenario: Narrow and medium omit it

- **WHEN** the same session renders at narrow and medium widths
- **THEN** no Cache Countdown section appears in either layout

### Requirement: Cache Countdown visibility and width-shed

The wide layout SHALL omit the Cache Countdown section AND its divider when `view.cache_countdown` is `None` (no cache event or expired), re-threading the row's elbows back to only the path divider. Independently, when the row cannot fit the path, rate-limit helper, Cache Countdown, and model section together, the Cache Countdown SHALL be shed FIRST — before the path is truncated further — and its divider dropped and re-threaded. When the Cache Countdown is shed for width, the path SHALL keep its normal truncation behaviour as if the section were never present.

#### Scenario: Hidden when expired drops the divider

- **WHEN** `view.cache_countdown` is `None`
- **THEN** the path/model row renders with only the path divider, and the top border / separator carry only the path elbow column (no cache elbow)

#### Scenario: Shed first under width pressure

- **WHEN** the row is too narrow to hold path + helper + Cache Countdown + model section, but wide enough for path + helper + model section
- **THEN** the Cache Countdown section and its divider are dropped, and the path renders without extra truncation caused by the section

### Requirement: Re-derived per render with no persisted state

The Cache Countdown SHALL be recomputed from the transcript and the frozen `now` on every render. The implementation SHALL NOT write, read, or depend on any per-session cache-state file; the anchor's sole source SHALL be the transcript scan already performed for token accounting.

#### Scenario: No cache-state file is created

- **WHEN** a wide render computes and displays the Cache Countdown
- **THEN** no per-session cache-state file is written under the Claude config directory
