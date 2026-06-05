## ADDED Requirements

### Requirement: Mon observer resolves session roots from CLAUDE_DIR

The `mon` observer SHALL derive the projects root and the statusline-output payloads root from `CLAUDE_DIR` (the same constant used by the statusline's main render path), rather than hardcoding `Path.home() / '.claude'`. When `CLAUDE_CONFIG_DIR` is set in the environment, `CLAUDE_DIR` resolves to that directory, and the `mon` observer SHALL find sessions and payloads there.

#### Scenario: Custom CLAUDE_CONFIG_DIR is respected

- **WHEN** `CLAUDE_CONFIG_DIR=/custom/claude` is set and sessions exist under `/custom/claude/projects/`
- **THEN** the observer discovers those sessions (rather than finding nothing under `~/.claude/projects/`)

#### Scenario: Default behaviour is unchanged

- **WHEN** `CLAUDE_CONFIG_DIR` is not set and sessions exist under `~/.claude/projects/`
- **THEN** the observer discovers sessions exactly as before

#### Scenario: Payloads root also uses CLAUDE_DIR

- **WHEN** `CLAUDE_CONFIG_DIR=/custom/claude` is set and payload files exist under `/custom/claude/statusline-output/`
- **THEN** the observer reads those payloads for session data
