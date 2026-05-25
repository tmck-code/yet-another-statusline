## ADDED Requirements

### Requirement: Burndown delta computation

The system SHALL compute a burndown delta for each active rate-limit bucket, defined as the difference (in percentage points) between the bucket's `used_percentage` and the ideal linear-burn percentage at the current point in the window.

The ideal linear-burn percentage SHALL be derived as:

```
window_start_ts = resets_at - window_minutes * 60
elapsed_minutes = (now - window_start_ts) / 60
ideal_pct       = (elapsed_minutes / window_minutes) * 100
delta           = used_percentage - ideal_pct
```

Window length SHALL be specified by the caller via a `window_minutes` argument. Module-level constants `FIVE_HOUR_MINUTES = 300` and `SEVEN_DAY_MINUTES = 10080` SHALL be used by callers for the 5h and 7d buckets respectively.

#### Scenario: Exact spec example
- **WHEN** `used_pct = 60.0`, `window_minutes = 300`, `resets_at` is 150 minutes in the future, `warmup_minutes = 5`
- **THEN** the helper returns a delta of `+10.5`

#### Scenario: Under pace
- **WHEN** `used_pct = 30.0`, `window_minutes = 300`, `resets_at` is 150 minutes in the future, `warmup_minutes = 5`
- **THEN** the helper returns a delta of `-19.5`

#### Scenario: Zero usage past warmup
- **WHEN** `used_pct = 0.0`, `window_minutes = 300`, `resets_at` is 120 minutes in the future (180 minutes elapsed), `warmup_minutes = 5`
- **THEN** the helper returns a delta of `-60.0`

### Requirement: Burndown suppression rules

The system SHALL suppress the burndown indicator (return `None` from the pure helper, return empty string from the renderer method) under any of the following conditions:

1. `resets_at == 0` — there is no active window.
2. `now >= resets_at` — the window has already expired.
3. `elapsed_minutes < warmup_minutes` — the window is too fresh to produce a meaningful trend.

Module-level warmup constants SHALL be `FIVE_HOUR_WARMUP_MINUTES = 5` and `SEVEN_DAY_WARMUP_MINUTES = 30`.

#### Scenario: No active window
- **WHEN** `resets_at = 0`
- **THEN** the helper returns `None`

#### Scenario: Expired window
- **WHEN** `resets_at` is in the past
- **THEN** the helper returns `None`

#### Scenario: Window in warmup
- **WHEN** `resets_at` is 297 minutes in the future and `window_minutes = 300` and `warmup_minutes = 5` (so `elapsed_minutes = 3`)
- **THEN** the helper returns `None`

#### Scenario: Window just past warmup
- **WHEN** `resets_at` is 294 minutes in the future and `window_minutes = 300` and `warmup_minutes = 5` (so `elapsed_minutes = 6`)
- **THEN** the helper returns a non-`None` delta

### Requirement: Burndown indicator format

When the burndown delta is not suppressed, the renderer SHALL format it as one of the following ANSI-coloured glyphs followed by the absolute delta to one decimal place and a `%` suffix:

- `▲<abs>%` when `delta > +0.5`
- `▼<abs>%` when `delta < -0.5`
- `·` when `|delta| ≤ 0.5` (the on-pace dot — no number rendered)

The arrow already encodes direction, so no `+`/`-` sign SHALL be rendered alongside the number.

#### Scenario: Over-burn formatting
- **WHEN** delta is `+10.5`
- **THEN** the rendered string strips to `▲10.5%`

#### Scenario: Under-burn formatting
- **WHEN** delta is `-19.5`
- **THEN** the rendered string strips to `▼19.5%`

#### Scenario: On-pace dot
- **WHEN** delta is `+0.3`
- **THEN** the rendered string strips to `·` (no percentage)

#### Scenario: On-pace dot at negative boundary
- **WHEN** delta is `-0.5`
- **THEN** the rendered string strips to `·`

### Requirement: Burndown colour buckets

The renderer SHALL colour the trend indicator using stepped, magnitude-ramped buckets that are symmetric across direction:

| `|delta|`    | `▲` colour          | `▼` colour    |
|--------------|---------------------|---------------|
| 0.5 – 5 %    | dim (safe palette)  | dim green     |
| 5 – 15 %     | warn palette        | mid green     |
| ≥ 15 %       | alert palette       | bright green  |
| ≤ 0.5 %      | dim grey (the `·` glyph) |              |

The renderer SHOULD re-use existing `Renderer.fill_colour` palette tones where possible rather than introducing new colour state.

#### Scenario: Over-burn safe bucket
- **WHEN** delta is `+3.0`
- **THEN** the trend is rendered with the safe (dim) ANSI tone

#### Scenario: Over-burn warn bucket
- **WHEN** delta is `+8.0`
- **THEN** the trend is rendered with the warn ANSI tone

#### Scenario: Over-burn alert bucket
- **WHEN** delta is `+20.0`
- **THEN** the trend is rendered with the alert ANSI tone

#### Scenario: Symmetric under-burn bucket
- **WHEN** delta is `-8.0`
- **THEN** the trend is rendered with the mid-green ANSI tone (same intensity bucket as `+8.0`)

### Requirement: Per-layout rendering policy

The system SHALL render the burndown indicator according to layout width:

- **Wide layout:** trend SHALL be rendered for both the 5h and 7d buckets.
- **Medium layout:** trend SHALL be rendered for the 5h bucket only.
- **Narrow layout:** trend SHALL NOT be rendered.

Where rendered, the trend SHALL be positioned immediately after the bucket's `<pct>%` and before any countdown (`T-<delta>` or `<h><m>m`).

#### Scenario: Wide layout shows both trends
- **WHEN** `model_right_section` is called with both buckets active and trend deltas of `+10.5` and `-3.2`
- **THEN** the helper text strips to a string containing `60% ▲10.5% T-` and the seven-day portion contains `▼3.2%`

#### Scenario: Medium layout shows 5h trend only
- **WHEN** `model_right_section_compact` is called with both buckets active
- **THEN** the rendered string contains the 5h trend indicator and does NOT contain a 7d trend indicator

#### Scenario: Narrow layout shows no trend
- **WHEN** the narrow-layout builder renders the rate-limit row
- **THEN** the rendered string contains neither a `▲` nor a `▼` glyph derived from burndown trend

### Requirement: Data model invariance

The system SHALL compute the burndown trend from existing `RateBucket` fields (`used_percentage`, `resets_at`) without introducing new fields on `RateBucket`, `RateLimits`, or `SessionInfo`. No upstream JSON schema change is required.

#### Scenario: No schema change required
- **WHEN** the session JSON payload contains only the existing `rate_limits.five_hour.used_percentage` and `rate_limits.five_hour.resets_at` fields
- **THEN** the trend SHALL still be computable and renderable correctly
