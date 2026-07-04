## MODIFIED Requirements

### Requirement: Reset-countdown placement and format

The 5-hour reset countdown SHALL be positioned at the front of the 5-hour segment, immediately after its icon and ahead of the usage and trend percentages, formatted as `(-H:MM)` — parenthesised, leading minus, hours kept, seconds dropped (e.g. `(-2:00)`, `(-0:45)`). When the limit has no reset (infinite/unknown), the existing infinite indicator SHALL render and no countdown SHALL appear.

When a burn-rate depletion estimate is available for the current 5-hour window (see the "5-hour burn-rate depletion estimate" requirement) AND the estimated time-to-depletion is strictly less than the time remaining until reset, the countdown SHALL render a **second countdown** inside the same single parenthesis group, joined to the reset countdown by `/-`, formatted with the same floor/`divmod` logic (hours kept, seconds dropped): `(-H:MM/-DH:DMM)` — e.g. `(-0:11/-0:04)` meaning the window resets in 11 minutes while tokens deplete in 4 minutes at the current rate. When no depletion estimate is available, when the estimate is not sooner than the reset, or when the layout provides no burn-rate value (medium/narrow layouts), the countdown SHALL render as the single reset countdown `(-H:MM)` only, byte-identical to the prior behaviour.

The reset-countdown portion and the enclosing parentheses SHALL keep the existing commit colour; only the appended `/-DH:DMM` depletion segment SHALL be drawn in a warn (near-100% fill) colour so it reads as a danger signal, with the colour reset back to the commit colour before the closing parenthesis. The depletion colour ANSI SHALL NOT be counted in any column-width computation (width is measured with the visible-width helper, not `len()`).

#### Scenario: Countdown leads the segment

- **WHEN** the 5-hour limit resets in 2 hours exactly with 30.0% used
- **THEN** the segment renders the timer icon, then `(-2:00)`, then `30.0%`, then the trend

#### Scenario: Under an hour keeps the single-digit hour

- **WHEN** the 5-hour limit resets in 45 minutes
- **THEN** the countdown renders as `(-0:45)`

#### Scenario: Depletion sooner than reset shows both countdowns

- **WHEN** the 5-hour window resets in 11 minutes, a positive burn-rate estimate puts depletion at 4 minutes, and depletion is sooner than reset
- **THEN** the countdown renders as `(-0:11/-0:04)` in a single parenthesis group with the `/-0:04` segment in the warn colour and the reset portion in the commit colour

#### Scenario: No burn-rate value renders the single countdown unchanged

- **WHEN** the layout supplies no burn-rate value (e.g. a medium/narrow render, or a wide render with fewer than two in-window samples)
- **THEN** the countdown renders as `(-H:MM)` only, byte-identical to the pre-change output, with no depletion segment and no warn colour

#### Scenario: Depletion not sooner than reset is suppressed

- **WHEN** a burn-rate estimate is available but the estimated time-to-depletion is greater than or equal to the time remaining until reset
- **THEN** only the single reset countdown `(-H:MM)` renders

## ADDED Requirements

### Requirement: 5-hour burn-rate depletion estimate

The statusline SHALL estimate time-to-depletion of the 5-hour token allowance from an **instantaneous** burn rate — the first-vs-last change in the account-wide 5-hour `used_percentage` over a short lookback window — expressed as percent-per-minute. This estimate SHALL be distinct from the existing burndown *deviation* (`used% - ideal%`); the deviation SHALL NOT be used as the depletion rate.

Sampling SHALL occur only in the wide layout, once per render, and SHALL be performed in the app/token-accounting layer (not in the renderer). Each sample SHALL append the observation time, the current 5-hour `resets_at`, and the current `used_percentage` to a persistent series under the configured Claude directory. The series SHALL be **global** — not keyed by session id — because the 5-hour `used_percentage` is account-wide and shared across sessions. Only samples whose `resets_at` matches the current window's `resets_at` SHALL contribute to the estimate, so a window rollover (a new `resets_at`) SHALL start a fresh series and discard stale samples. The retained sample history SHALL be at least as long as the lookback window so that a needed sample is not pruned before use.

The burn rate SHALL be computed as `(used_last - used_first) / ((t_last - t_first) / 60)` over the samples within the lookback window. The estimate SHALL be unavailable (yielding no depletion countdown) when fewer than two in-window samples exist, when their time span is below a minimum floor (`DT_FLOOR`), when the current window has no `resets_at`, or when the rate is not strictly positive. When available, the time-to-depletion in minutes SHALL be `(100 - used_percentage) / rate_per_minute`, computed by a single pure helper alongside `burndown_delta`.

The lookback window SHALL be governed by the `five_hour_rate_window` configuration knob (see `statusline-config`), defaulting to 300 seconds. `DT_FLOOR` SHALL be a fixed minimum-span guard, not a user-facing knob.

#### Scenario: Rising usage yields a positive rate and a depletion estimate

- **WHEN** two or more in-window samples for the current `resets_at` show `used_percentage` rising over a span of at least `DT_FLOOR`
- **THEN** a positive percent-per-minute rate is computed and time-to-depletion is `(100 - used_percentage) / rate`

#### Scenario: Window rollover discards the stale series

- **WHEN** the current `resets_at` differs from the `resets_at` recorded on earlier samples
- **THEN** those earlier samples are excluded and the estimate is computed only from samples matching the current `resets_at`

#### Scenario: Fewer than two samples yields no estimate

- **WHEN** only one in-window sample exists for the current `resets_at`
- **THEN** no burn rate is produced and no depletion countdown is shown

#### Scenario: Sub-floor span yields no estimate

- **WHEN** two in-window samples exist but their time span is below `DT_FLOOR`
- **THEN** no burn rate is produced and no depletion countdown is shown

#### Scenario: Global series spans sessions

- **WHEN** samples are recorded under two different session ids for the same `resets_at`
- **THEN** all of them contribute to the single global series used for the estimate
