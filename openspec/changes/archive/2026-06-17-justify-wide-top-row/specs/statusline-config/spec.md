## ADDED Requirements

### Requirement: justify layout knob

The statusline SHALL support a `justify` boolean knob that controls whether the wide layout distributes horizontal slack evenly across top-row sections. The knob SHALL resolve through the standard precedence chain: `YAS_JUSTIFY` environment variable → `[layout].justify` in `yas.toml` → built-in default of `false`. The env var SHALL accept the same boolean forms as other boolean knobs (`1`/`0`/`true`/`false`). An invalid value SHALL cause the knob to fall back to `false` and be recorded in debug output; a `yas.toml`-sourced rejection SHALL also be surfaced in the visible config-error row. The constant `DEFAULT_JUSTIFY = False` SHALL be defined in `constants.py` and imported by `config.py`.

#### Scenario: Default is false

- **WHEN** no `YAS_JUSTIFY` env var is set and no `[layout].justify` key exists in `yas.toml`
- **THEN** `cfg.justify` is `false` and the wide layout behaves as before

#### Scenario: Env var enables justify

- **WHEN** `YAS_JUSTIFY=1` is set in the environment
- **THEN** `cfg.justify` is `true`

#### Scenario: yas.toml enables justify

- **WHEN** `yas.toml` contains `[layout]` with `justify = true` and no `YAS_JUSTIFY` env var is set
- **THEN** `cfg.justify` is `true`

#### Scenario: Env var overrides yas.toml

- **WHEN** `YAS_JUSTIFY=0` is set in the environment and `[layout].justify = true` is in `yas.toml`
- **THEN** `cfg.justify` is `false`

#### Scenario: Invalid env value falls back to default

- **WHEN** `YAS_JUSTIFY=banana` is set
- **THEN** `cfg.justify` is `false` and the rejection is recorded in debug output
