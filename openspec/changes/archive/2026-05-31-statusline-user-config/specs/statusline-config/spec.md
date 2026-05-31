## ADDED Requirements

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
- **THEN** every knob resolves to its built-in default (`max_width=140`, `full_width=false`, `soft_limit=150000`, `token_window=60`, `theme=dark`, `bg_shift=warm`)

#### Scenario: CLI flag overrides env and config

- **WHEN** `--theme` is passed on the command line and `YAS_THEME` and `[appearance].theme` are also set
- **THEN** the CLI `--theme` value is used

### Requirement: Canonical env vars and deprecated aliases

The statusline SHALL accept canonical `YAS_*` environment variables for all six knobs (`YAS_MAX_WIDTH`, `YAS_FULL_WIDTH`, `YAS_SOFT_LIMIT`, `YAS_TOKEN_WINDOW`, `YAS_THEME`, `YAS_BG_SHIFT`). It SHALL continue to honor the legacy aliases `STATUSLINE_TOKEN_WINDOW` (for `token_window`) and `CLAUDE_STATUSLINE_THEME` (for `theme`). When both a canonical var and its alias are set, the canonical value SHALL win.

#### Scenario: Legacy alias still works

- **WHEN** only `STATUSLINE_TOKEN_WINDOW=30` is set
- **THEN** the resolved `token_window` is `30`

#### Scenario: Canonical wins over alias

- **WHEN** `YAS_TOKEN_WINDOW=45` and `STATUSLINE_TOKEN_WINDOW=30` are both set
- **THEN** the resolved `token_window` is `45`

#### Scenario: Theme alias resolves

- **WHEN** only `CLAUDE_STATUSLINE_THEME` names a known theme
- **THEN** that theme is used

### Requirement: yas.toml location and sectioned schema

The statusline SHALL read configuration from `yas.toml` located in `CLAUDE_CONFIG_DIR` (defaulting to `~/.claude/`). The file SHALL use a sectioned schema: `[layout]` for `max_width` and `full_width`, `[tokens]` for `soft_limit` (global default) and `token_window`, an optional `[[tokens.model]]` array of `{ match, soft_limit }` tables for per-model `soft_limit` overrides, and `[appearance]` for `theme` and `bg_shift`. Absence of the file SHALL be equivalent to all-defaults and SHALL NOT be an error.

#### Scenario: Knobs read from their sections

- **WHEN** `yas.toml` contains `[layout]` `max_width = 200`, `[tokens]` `soft_limit = 1000000`, and `[appearance]` `theme = "dark"`
- **THEN** those three values are resolved from the file

#### Scenario: Missing file is not an error

- **WHEN** no `yas.toml` exists in `CLAUDE_CONFIG_DIR`
- **THEN** the statusline renders normally using env + defaults and reports no config error

#### Scenario: Unknown keys and sections are ignored

- **WHEN** `yas.toml` contains a key or section that does not map to a known knob
- **THEN** the unknown entry is ignored and the rest of the config still resolves

### Requirement: TOML parsing with graceful 3.10 degradation

The statusline SHALL parse `yas.toml` using the standard-library `tomllib` module and SHALL remain zero-dependency. On a Python runtime where `tomllib` is unavailable (3.10), the statusline SHALL skip the `yas.toml` file silently and resolve every knob from env + defaults; it SHALL NOT crash and SHALL NOT add any third-party dependency.

#### Scenario: TOML applied on 3.11+

- **WHEN** the runtime provides `tomllib` and a valid `yas.toml` exists
- **THEN** the file's values participate in precedence resolution

#### Scenario: File skipped on 3.10

- **WHEN** the runtime does not provide `tomllib` and a `yas.toml` exists
- **THEN** the file is ignored, env + defaults are used, and the statusline renders without error

### Requirement: Fail-safe validation of config values

The statusline SHALL never crash or render garbage because of bad configuration. A syntactically broken `yas.toml` SHALL cause the entire file to be ignored (env + defaults still apply). A value that is the wrong type or out of range for its knob SHALL cause only that single knob to fall back to its default while all other valid knobs are still applied. Validation rules: `max_width` is an integer > 0; `full_width` is a boolean (env form accepts any non-empty value as true); `soft_limit` is an integer > 0; `token_window` is a number > 0; `theme` must be a known theme name; `bg_shift` must be one of `warm` or `cool`.

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

#### Scenario: Malformed per-model entry dropped

- **WHEN** a `[[tokens.model]]` entry has a missing/empty `match`, or a `soft_limit` that is non-integer or `<= 0`
- **THEN** only that entry is dropped (models it would have matched fall back to the global `soft_limit`), valid entries still apply, and the rejection is recorded referencing the entry (e.g. `tokens.model[2]`)

### Requirement: Per-model soft_limit resolution

The statusline SHALL support per-model `soft_limit` overrides declared as a `[[tokens.model]]` array of tables, each with a `match` string and a `soft_limit` integer. At render time the statusline SHALL select the effective `soft_limit` for the session's model by matching each entry's `match` as a case-insensitive plain substring against the lowercased model `id` and `display_name`; when multiple entries match, the entry with the longest `match` string SHALL win, and ties SHALL be broken by file order (first entry wins). `match` SHALL be a literal substring (no glob or regex). When no entry matches, the global `soft_limit` SHALL be used. A matching per-model override SHALL take precedence over the global value from ANY source, including the `YAS_SOFT_LIMIT` environment variable (specificity beats source precedence; this is the single documented exception to the env > toml rule). Per-model overrides SHALL be expressible only in `yas.toml`; there SHALL be no per-model environment variable.

#### Scenario: Most-specific match wins

- **WHEN** entries `match="opus"` (200000) and `match="opus-4-8[1m]"` (1000000) are present and the session model id is `claude-opus-4-8[1m]`
- **THEN** the effective `soft_limit` is `1000000` (the longer `match="opus-4-8[1m]"` wins over `match="opus"`)

#### Scenario: Falls back to global when no entry matches

- **WHEN** only `match="haiku"` overrides exist and the session model is an Opus model
- **THEN** the effective `soft_limit` is the resolved global value

#### Scenario: Matches against display_name as well as id

- **WHEN** an entry `match="1m context"` is present and the model `display_name` is `Opus 4.8 (1M context)`
- **THEN** that entry matches (case-insensitive) and its `soft_limit` is used

#### Scenario: Per-model toml beats global env

- **WHEN** `YAS_SOFT_LIMIT=200000` is set in the environment and a matching entry `match="1m", soft_limit=1000000` exists for a 1M-context session
- **THEN** the effective `soft_limit` is `1000000`

#### Scenario: Tie broken by file order

- **WHEN** two entries have equal-length `match` strings that both match the model
- **THEN** the entry appearing first in the file is used

### Requirement: Visible config-error row

When one or more configuration values are rejected, the statusline SHALL append a single compact error row at the bottom of the box, inside the border, naming the rejected knobs and truncated to the render width (e.g. `⚠ yas.toml: 2 values ignored (max_width, bg_shift)`). The row SHALL appear in all layouts (narrow, medium, wide). The error row SHALL NOT appear when no value was rejected. Full per-value reasons SHALL be written to stderr only when `YAS_DEBUG` is set in the environment.

#### Scenario: Error row shown on rejection

- **WHEN** two configured values are rejected
- **THEN** a single error row is appended above the bottom border naming the two rejected knobs

#### Scenario: No error row when config is clean

- **WHEN** all configured values are valid (or no config is present)
- **THEN** no error row is rendered

#### Scenario: Detailed reasons gated by YAS_DEBUG

- **WHEN** a value is rejected and `YAS_DEBUG` is set
- **THEN** a per-value reason line is written to stderr in addition to the compact row

#### Scenario: Error row appears in narrow layout

- **WHEN** a value is rejected and the terminal is narrow
- **THEN** the compact error row is still appended, truncated to the narrow width without breaking the box

### Requirement: Single source of resolved configuration

The statusline SHALL expose resolved configuration through one frozen `Config` object loaded once, and the existing module-level constants that callers and tests depend on (`MAX_WIDTH`, `SOFT_LIMIT`, the token-rate window) SHALL be sourced from that object so that current behaviour and module-reload tests continue to work. The module-level `SOFT_LIMIT` SHALL hold the resolved *global* value; per-model resolution SHALL be performed at render time via a `Config` method (e.g. `soft_limit_for(model_name)`) whose result is threaded into the rendering paths, not via the module constant. Layout breakpoints (narrow/medium/min width) SHALL remain hardcoded and SHALL NOT be user-configurable.

#### Scenario: Module constant holds the global value

- **WHEN** `YAS_MAX_WIDTH` and `YAS_SOFT_LIMIT` are set and the module is loaded
- **THEN** `MAX_WIDTH` equals the resolved value and `SOFT_LIMIT` equals the resolved global `soft_limit` (independent of any per-model overrides)

#### Scenario: Layout breakpoints are not configurable

- **WHEN** a user attempts to set a narrow/medium/min width via env or `yas.toml`
- **THEN** the layout breakpoints are unchanged (the setting has no effect)
