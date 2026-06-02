# No Specification Changes Required

## Rationale

This change expands the available hardcoded themes from 4 to 13 but does not introduce new capabilities or modify spec-level behavior.

Theme selection is fully governed by the existing `statusline-config` specification, which:
- Defines the configuration precedence chain (CLI → env → config file → defaults)
- Specifies that theme names must be "known"
- Requires validation that a theme name is in the set of known themes

This change only expands the set of valid theme names. The resolution logic, validation rules, and configuration behavior remain identical.

## Impact

- `statusline-config` requirement "theme must be a known theme name" now accepts: `claude-dark`, `claude-light`, `dracula`, `gruvbox-dark`, `gruvbox-light`, `nord`, `one-dark`, `one-light`, `solarized-dark`, `solarized-light`, `tokyo-night`, `palenight` (was: only the first 2 + 2 catppuccin variants)
- No change to the requirement's enforcement or precedence logic
- No change to the `--theme` CLI flag, `YAS_THEME` env var, `[appearance].theme` config file key, or `CLAUDE_STATUSLINE_THEME` legacy alias behavior
