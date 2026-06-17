## ADDED Requirements

### Requirement: Section-labels knob

The statusline SHALL expose a boolean `labels` knob that toggles wide-layout section labels. It SHALL resolve through the standard precedence chain: canonical `YAS_LABELS` environment variable → `[layout].labels` in `yas.toml` → built-in default `false`. The resolved value SHALL be exposed as `cfg.labels` on the frozen `Config`. An absent or unparseable source SHALL fall through to the next, ending at the `false` default. The knob SHALL accept the same boolean spellings as other boolean knobs (`1`/`0`/`true`/`false`, case-insensitive, for env values; native booleans in `yas.toml`).

#### Scenario: Default is false

- **WHEN** no `yas.toml` sets `[layout].labels` and `YAS_LABELS` is unset
- **THEN** the resolved `cfg.labels` is `false`

#### Scenario: Config file enables labels

- **WHEN** `[layout].labels = true` is set in `yas.toml` and `YAS_LABELS` is unset
- **THEN** the resolved `cfg.labels` is `true`

#### Scenario: Env overrides config file

- **WHEN** `[layout].labels = true` is set in `yas.toml` and `YAS_LABELS=0` is set in the environment
- **THEN** the resolved `cfg.labels` is `false`

#### Scenario: Invalid value falls through to default

- **WHEN** `YAS_LABELS=maybe` is set and nothing else configures the knob
- **THEN** the resolved `cfg.labels` is `false`
