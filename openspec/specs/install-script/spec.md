## ADDED Requirements

### Requirement: Single install script with two modes

The repository SHALL provide a single executable bash script at `ops/install.sh` that operates in one of two modes — full mode or wire-only mode — and that serves as the single source of truth for wiring YAS into Claude Code. The same script SHALL be runnable both by a human via `curl … | bash` and by the `yas:init` skill.

#### Scenario: Mode auto-detection via CLAUDE_PLUGIN_ROOT

- **WHEN** the script runs with the `CLAUDE_PLUGIN_ROOT` environment variable set and no overriding flag
- **THEN** it selects wire-only mode and skips all plugin-management steps

#### Scenario: Default to full mode

- **WHEN** the script runs with `CLAUDE_PLUGIN_ROOT` unset and no overriding flag
- **THEN** it selects full mode (marketplace + plugin management followed by settings wiring)

#### Scenario: Explicit mode override

- **WHEN** the script is invoked with `--wire-only` or `--full`
- **THEN** that flag overrides the `CLAUDE_PLUGIN_ROOT`-based auto-detection

### Requirement: curl-pipe bootstrap entrypoint

The script SHALL be installable by humans via a single command that fetches it from the repository's default branch and pipes it to bash:

```
curl -fsSL https://raw.githubusercontent.com/tmck-code/yet-another-statusline/main/ops/install.sh | bash
```

This entrypoint SHALL run full mode, installing the latest plugin version served by the marketplace using the latest installer on the branch. The script SHALL NOT perform any release-tag pinning or self-re-execution.

#### Scenario: curl bootstrap runs unattended

- **WHEN** a user pipes the branch copy of `ops/install.sh` to bash on a machine where YAS is not yet installed
- **THEN** the script completes the full flow without requiring interactive input

### Requirement: Full-mode plugin orchestration

In full mode the script SHALL ensure the marketplace and plugin are present and current before wiring settings, branching on inspection of Claude Code's on-disk state.

#### Scenario: Marketplace absent

- **WHEN** `known_marketplaces.json` does not contain the `yet-another-statusline` key
- **THEN** the script runs `claude plugin marketplace add tmck-code/yet-another-statusline`

#### Scenario: Marketplace already present

- **WHEN** `known_marketplaces.json` already contains the `yet-another-statusline` key
- **THEN** the script does not re-add the marketplace

#### Scenario: Plugin not installed

- **WHEN** `installed_plugins.json` does not contain `yas@yet-another-statusline`
- **THEN** the script runs `claude plugin install yas@yet-another-statusline --scope user`

#### Scenario: Plugin already installed

- **WHEN** `installed_plugins.json` already contains `yas@yet-another-statusline`
- **THEN** the script runs `claude plugin update yas@yet-another-statusline --scope user`

#### Scenario: All plugin CLI invocations are user-scoped

- **WHEN** the script shells `claude plugin marketplace add`, `install`, or `update`
- **THEN** it passes `--scope user` explicitly on the install and update commands

### Requirement: Wire-only settings write

In both modes the script SHALL write `statusLine.command` into `settings.json` under `$CLAUDE_CONFIG_DIR` (default `~/.claude/`), pointing at the newest installed renderer, and SHALL do so safely. In wire-only mode it SHALL target the renderer under `CLAUDE_PLUGIN_ROOT` directly without scanning, and SHALL NOT perform plugin management, network access, or nested `claude` invocations.

#### Scenario: Renderer discovery in full mode

- **WHEN** the script wires settings in full mode
- **THEN** it locates the newest plugin root whose `claude/statusline_command.py` exists on disk, preferring `installed_plugins.json` and falling back to a version-sorted cache scan

#### Scenario: Atomic write with backup

- **WHEN** `settings.json` already exists and its `statusLine.command` differs from the target
- **THEN** the script backs the file up, writes the new value via a temp file and atomic rename, and validates the result

#### Scenario: Exact-match skip

- **WHEN** the existing `statusLine.command` exactly equals the target command
- **THEN** the script makes no change and reports the skip

#### Scenario: Corrupt write rollback

- **WHEN** the written `settings.json` fails JSON validation
- **THEN** the script restores the pre-write backup and exits non-zero

#### Scenario: Legacy file cleanup

- **WHEN** legacy `statusline-info-*` files exist under `$CLAUDE_CONFIG_DIR`
- **THEN** the script removes them

#### Scenario: Missing Python interpreter

- **WHEN** no Python 3.10+ interpreter is found on PATH
- **THEN** the script reports the error and exits non-zero without modifying `settings.json`

### Requirement: Dry-run mode

The script SHALL support a `--dry-run` flag that prints the intended actions for the selected mode without shelling `claude` or modifying `settings.json`.

#### Scenario: Dry-run prints decisions only

- **WHEN** the script runs with `--dry-run`
- **THEN** it prints whether it would add the marketplace, install vs update the plugin, and wire settings, but performs none of those side effects

### Requirement: Per-mode preflight and strictness

The script SHALL run under `set -uo pipefail`, check only the dependencies its selected mode needs, and remain portable across macOS and Linux.

#### Scenario: Full-mode dependency check

- **WHEN** full mode runs and `claude` is not on PATH
- **THEN** the script reports the missing dependency with an install hint and exits non-zero

#### Scenario: Wire-only dependency check

- **WHEN** wire-only mode runs
- **THEN** the script does not require `claude` or `curl` to be present, only `jq` and a Python interpreter

### Requirement: Skill delegates to the script

The `yas:init` skill SHALL delegate its wiring work to `ops/install.sh` rather than carrying an inline implementation, preserving its observable behaviour of writing a wire-only `statusLine.command`.

#### Scenario: Skill invokes the shipped script

- **WHEN** the `yas:init` skill runs
- **THEN** it invokes `bash "${CLAUDE_PLUGIN_ROOT}/ops/install.sh"`, which detects wire-only mode and writes `settings.json` against that plugin root
