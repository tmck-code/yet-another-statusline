## ADDED Requirements

### Requirement: Recording knob

The resolved `Config` SHALL carry a boolean `recording` knob, default `false`,
resolved through the standard precedence chain from the canonical environment
variable `YAS_RECORDING` and then the `yas.toml` key `enabled` in a new top-level
`[recording]` table. The knob SHALL have no CLI flag and no legacy environment
alias. It SHALL be parsed with the same boolean parser as the other boolean
knobs, so `1`, `true`, `yes`, and `on` enable it, and an empty environment value
SHALL count as absent. An unparseable value SHALL fall back to the default and
SHALL surface in the config-error row only when its origin is `yas.toml`,
matching every other knob.

#### Scenario: Default is off

- **WHEN** no `yas.toml` exists and `YAS_RECORDING` is unset
- **THEN** `Config.load(...).recording` is `False`

#### Scenario: TOML enables recording

- **WHEN** `yas.toml` contains `[recording]` with `enabled = true`
- **THEN** the resolved `recording` is `True`

#### Scenario: Env var overrides TOML

- **WHEN** `yas.toml` sets `[recording] enabled = true` and the environment sets
  `YAS_RECORDING=0`
- **THEN** the resolved `recording` is `False`

#### Scenario: Empty env value is absent

- **WHEN** `YAS_RECORDING` is set to the empty string and `yas.toml` sets
  `[recording] enabled = true`
- **THEN** the resolved `recording` is `True`, because the empty env value counts
  as absent

#### Scenario: Invalid TOML value falls back and is reported

- **WHEN** `yas.toml` sets `[recording] enabled = "maybe"`
- **THEN** `recording` is `False`
- **AND** a config error is recorded for display in the config-error row

#### Scenario: Invalid env value falls back quietly

- **WHEN** `YAS_RECORDING` is set to `maybe`
- **THEN** `recording` is `False` and the rejection appears only in the debug
  lines, not in the error row
