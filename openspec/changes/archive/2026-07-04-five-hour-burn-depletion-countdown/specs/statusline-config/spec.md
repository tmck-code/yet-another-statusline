## ADDED Requirements

### Requirement: five_hour_rate_window knob

The statusline SHALL expose a `five_hour_rate_window` configuration knob controlling the lookback window (in seconds) over which the instantaneous 5-hour burn rate is measured. It SHALL resolve through the standard layered precedence (env → `yas.toml` → default): the canonical env var `YAS_FIVE_HOUR_RATE_WINDOW`, the legacy alias `STATUSLINE_FIVE_HOUR_RATE_WINDOW`, and the `[tokens].five_hour_rate_window` TOML key, defaulting to `300`. When both the canonical env var and its legacy alias are set, the canonical value SHALL win. The value SHALL be validated as a number greater than 0; an invalid or out-of-range value SHALL fall back to the default of `300` without affecting any other knob, consistent with the fail-safe validation rule for `token_window`. The resolved value SHALL be exposed as a single field on the resolved `Config`.

#### Scenario: Default when unset

- **WHEN** no env var and no `yas.toml` key set `five_hour_rate_window`
- **THEN** the resolved `five_hour_rate_window` is `300`

#### Scenario: Env var override

- **WHEN** `YAS_FIVE_HOUR_RATE_WINDOW=120` is set in the environment
- **THEN** the resolved `five_hour_rate_window` is `120`

#### Scenario: Legacy alias honoured, canonical wins

- **WHEN** `STATUSLINE_FIVE_HOUR_RATE_WINDOW=90` is set and no canonical var is present
- **THEN** the resolved `five_hour_rate_window` is `90`
- **AND WHEN** both `YAS_FIVE_HOUR_RATE_WINDOW=120` and `STATUSLINE_FIVE_HOUR_RATE_WINDOW=90` are set
- **THEN** the resolved `five_hour_rate_window` is `120`

#### Scenario: TOML source

- **WHEN** `yas.toml` sets `[tokens].five_hour_rate_window = 240` and no env var overrides it
- **THEN** the resolved `five_hour_rate_window` is `240`

#### Scenario: Invalid value falls back to default

- **WHEN** `five_hour_rate_window` is set to a non-numeric or non-positive value
- **THEN** only `five_hour_rate_window` falls back to `300` while all other valid knobs still apply
