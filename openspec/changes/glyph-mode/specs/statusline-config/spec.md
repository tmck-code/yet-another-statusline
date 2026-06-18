## ADDED Requirements

### Requirement: Glyph mode knob

The statusline SHALL expose a `glyph_mode` knob that selects the glyph rendering mode, resolved through the standard precedence chain: CLI `--glyph-mode <value>` → `YAS_GLYPH_MODE` env var → `[appearance].glyph_mode` in `yas.toml` → default. The accepted values SHALL be exactly `nerdfont`, `ascii`, `unicode`, and `singlewidth` (case-insensitive), and the default SHALL be `nerdfont`. Any other value SHALL be rejected and fall back to the default like every other knob. There SHALL be no per-mode environment variable beyond `YAS_GLYPH_MODE`.

#### Scenario: Env var selects a mode

- **WHEN** `YAS_GLYPH_MODE=ascii` is set
- **THEN** the resolved `glyph_mode` is `ascii`

#### Scenario: CLI flag overrides env and toml

- **WHEN** `--glyph-mode unicode` is passed and `YAS_GLYPH_MODE=ascii` and `[appearance].glyph_mode = "nerdfont"` are also set
- **THEN** the resolved `glyph_mode` is `unicode`

#### Scenario: Default is nerdfont

- **WHEN** no `glyph_mode` is configured from any source
- **THEN** the resolved `glyph_mode` is `nerdfont`

#### Scenario: Unknown mode rejected

- **WHEN** `glyph_mode = "fancy"` is configured
- **THEN** `glyph_mode` falls back to `nerdfont` and the rejection is recorded

## MODIFIED Requirements

### Requirement: Layered configuration precedence

The statusline SHALL resolve every configurable knob through a single, fixed precedence chain: CLI flag (where one exists) → canonical `YAS_*` environment variable → legacy-alias environment variable → `yas.toml` value → built-in default. A higher-precedence source that is present and valid SHALL override all lower sources for that knob; an absent or invalid source SHALL fall through to the next.

#### Scenario: Env overrides config file

- **WHEN** `[layout].max_width = 200` is set in `yas.toml` and `YAS_MAX_WIDTH=160` is set in the environment
- **THEN** the resolved `max_width` is `160`

#### Scenario: Config file overrides default

- **WHEN** `[tokens].soft_limit = 1000000` is set in `yas.toml` and no `YAS_SOFT_LIMIT` env var is set
- **THEN** the resolved `soft_limit` is `1000000`

#### Scenario: Default when nothing is set

- **WHEN** no `yas.toml` exists and no relevant env var is set
- **THEN** every knob resolves to its built-in default (`max_width=140`, `full_width=false`, `soft_limit=150000`, `token_window=60`, `theme=dark`, `bg_shift=warm`, `show_day_stats=true`, `glyph_mode=nerdfont`)

#### Scenario: CLI flag overrides env and config

- **WHEN** `--theme` is passed on the command line and `YAS_THEME` and `[appearance].theme` are also set
- **THEN** the CLI `--theme` value is used

### Requirement: Canonical env vars and deprecated aliases

The statusline SHALL accept canonical `YAS_*` environment variables for all eight knobs (`YAS_MAX_WIDTH`, `YAS_FULL_WIDTH`, `YAS_SOFT_LIMIT`, `YAS_TOKEN_WINDOW`, `YAS_THEME`, `YAS_BG_SHIFT`, `YAS_SHOW_DAY_STATS`, `YAS_GLYPH_MODE`). It SHALL continue to honor the legacy aliases `STATUSLINE_TOKEN_WINDOW` (for `token_window`) and `CLAUDE_STATUSLINE_THEME` (for `theme`). When both a canonical var and its alias are set, the canonical value SHALL win.

#### Scenario: Legacy alias still works

- **WHEN** only `STATUSLINE_TOKEN_WINDOW=30` is set
- **THEN** the resolved `token_window` is `30`

#### Scenario: Canonical wins over alias

- **WHEN** `YAS_TOKEN_WINDOW=45` and `STATUSLINE_TOKEN_WINDOW=30` are both set
- **THEN** the resolved `token_window` is `45`

#### Scenario: Theme alias resolves

- **WHEN** only `CLAUDE_STATUSLINE_THEME` names a known theme
- **THEN** that theme is used

#### Scenario: Day-stats env var resolves

- **WHEN** `YAS_SHOW_DAY_STATS=0` is set
- **THEN** the resolved `show_day_stats` is `false`

#### Scenario: Glyph-mode env var resolves

- **WHEN** `YAS_GLYPH_MODE=unicode` is set
- **THEN** the resolved `glyph_mode` is `unicode`

### Requirement: yas.toml location and sectioned schema

The statusline SHALL read configuration from `yas.toml` located in `CLAUDE_CONFIG_DIR` (defaulting to `~/.claude/`). The file SHALL use a sectioned schema: `[layout]` for `max_width` and `full_width`, `[tokens]` for `soft_limit` (global default), `token_window`, and `show_day_stats`, an optional `[[tokens.model]]` array of `{ match, soft_limit }` tables for per-model `soft_limit` overrides, and `[appearance]` for `theme`, `bg_shift`, and `glyph_mode`. Absence of the file SHALL be equivalent to all-defaults and SHALL NOT be an error.

#### Scenario: Knobs read from their sections

- **WHEN** `yas.toml` contains `[layout]` `max_width = 200`, `[tokens]` `soft_limit = 1000000`, and `[appearance]` `theme = "dark"`
- **THEN** those three values are resolved from the file

#### Scenario: Day-stats read from tokens section

- **WHEN** `yas.toml` contains `[tokens]` `show_day_stats = false` and no `YAS_SHOW_DAY_STATS` env var is set
- **THEN** the resolved `show_day_stats` is `false`

#### Scenario: Glyph-mode read from appearance section

- **WHEN** `yas.toml` contains `[appearance]` `glyph_mode = "ascii"` and no `YAS_GLYPH_MODE` env var is set
- **THEN** the resolved `glyph_mode` is `ascii`

#### Scenario: Missing file is not an error

- **WHEN** no `yas.toml` exists in `CLAUDE_CONFIG_DIR`
- **THEN** the statusline renders normally using env + defaults and reports no config error

#### Scenario: Unknown keys and sections are ignored

- **WHEN** `yas.toml` contains a key or section that does not map to a known knob
- **THEN** the unknown entry is ignored and the rest of the config still resolves

### Requirement: Fail-safe validation of config values

The statusline SHALL never crash or render garbage because of bad configuration. A syntactically broken `yas.toml` SHALL cause the entire file to be ignored (env + defaults still apply). A value that is the wrong type or out of range for its knob SHALL cause only that single knob to fall back to its default while all other valid knobs are still applied. Validation rules: `max_width` is an integer > 0; `full_width` is a boolean (env form accepts any non-empty value as true); `soft_limit` is an integer > 0; `token_window` is a number > 0; `theme` must be a known theme name; `bg_shift` must be one of `warm` or `cool`; `show_day_stats` is a boolean (env form treats `0`, `false`, and `no` as false and any other non-empty value as true); `glyph_mode` must be one of `nerdfont`, `ascii`, `unicode`, or `singlewidth`.

#### Scenario: Broken TOML ignores whole file

- **WHEN** `yas.toml` contains a TOML syntax error
- **THEN** no value from the file is applied, env + defaults are used, and a config error is recorded

#### Scenario: One bad value falls back, others apply

- **WHEN** `yas.toml` sets `max_width = "banana"` (invalid) and `soft_limit = 1000000` (valid)
- **THEN** `max_width` resolves to its default and `soft_limit` resolves to `1000000`

#### Scenario: Out-of-range value rejected

- **WHEN** `soft_limit = -5` is configured
- **THEN** `soft_limit` falls back to its default and the rejection is recorded

#### Scenario: Unknown enum value rejected

- **WHEN** `bg_shift = "purple"` is configured
- **THEN** `bg_shift` falls back to `warm` and the rejection is recorded

#### Scenario: Unknown glyph-mode value rejected

- **WHEN** `[appearance].glyph_mode = "fancy"` is configured
- **THEN** `glyph_mode` falls back to `nerdfont` and the rejection is recorded

#### Scenario: Non-boolean day-stats rejected

- **WHEN** `[tokens].show_day_stats = "banana"` is configured
- **THEN** `show_day_stats` falls back to its default (`true`) and the rejection is recorded

#### Scenario: Malformed per-model entry dropped

- **WHEN** a `[[tokens.model]]` entry has a missing/empty `match`, or a `soft_limit` that is non-integer or `<= 0`
- **THEN** only that entry is dropped (models it would have matched fall back to the global `soft_limit`), valid entries still apply, and the rejection is recorded referencing the entry (e.g. `tokens.model[2]`)
