## MODIFIED Requirements

### Requirement: Wire-only settings write

In both modes the script SHALL write `statusLine.command` into `settings.json` under `$CLAUDE_CONFIG_DIR` (default `~/.claude/`), pointing at the newest installed renderer, and SHALL do so safely. In wire-only mode it SHALL target the renderer under `CLAUDE_PLUGIN_ROOT` directly without scanning, and SHALL NOT perform plugin management, network access (other than the `uv`/CPython provisioning described under "Private interpreter provisioning"), or nested `claude` invocations. All JSON reads, transforms, and validation SHALL be performed through the resolved Python interpreter and SHALL NOT depend on `jq` or any other external JSON tool.

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

#### Scenario: Existing settings keys preserved

- **WHEN** `settings.json` already contains unrelated top-level keys
- **THEN** the script merges `statusLine` in without dropping or altering those keys

#### Scenario: JSON handling needs no jq

- **WHEN** the script reads, merges, or validates `settings.json` (or `known_marketplaces.json` / `installed_plugins.json`)
- **THEN** it does so via the resolved Python interpreter and never shells `jq`, so the flow succeeds on a machine where `jq` is absent

#### Scenario: Values are passed safely to the JSON helper

- **WHEN** the script passes a file path or a value (such as the command string) into the Python JSON helper
- **THEN** it passes them as process arguments (argv), never string-interpolated into the Python source, so paths or values containing quotes, backslashes, or shell metacharacters cannot corrupt the JSON or inject code

### Requirement: Per-mode preflight and strictness

The script SHALL run under `set -uo pipefail`, check only the dependencies its selected mode needs, and remain portable across macOS and Linux. The preflight substrate gate SHALL be the presence of a system Python ≥3.10 (the bootstrap substrate), NOT the presence of `uv` and NOT the presence of `jq`.

#### Scenario: Full-mode dependency check

- **WHEN** full mode runs and `claude` is not on PATH
- **THEN** the script reports the missing dependency with an install hint and exits non-zero

#### Scenario: Wire-only dependency check

- **WHEN** wire-only mode runs
- **THEN** the script does not require `claude`, `curl`, or `jq` to be present, only a system Python interpreter ≥3.10

#### Scenario: Missing Python substrate

- **WHEN** no system Python ≥3.10 interpreter is found on PATH
- **THEN** the script reports the error and exits non-zero without modifying `settings.json`

#### Scenario: uv is not a preflight precondition

- **WHEN** preflight runs on a machine that has a system Python ≥3.10 but no `uv` on PATH
- **THEN** preflight passes (it does not reject for a missing `uv`), because `uv` is bootstrapped later during provisioning

## ADDED Requirements

### Requirement: Private interpreter provisioning via uv

The script SHALL provision a private, plugin-local CPython under `$PLUGIN_ROOT/.python` using `uv`, and wire `statusLine.command` to that interpreter for the fastest statusline startup, without mutating the user's system Python, shell rc, or PATH. `uv` SHALL be the guaranteed provisioning engine: when `uv` is already on PATH the script SHALL use it; when `uv` is absent the script SHALL bootstrap a plugin-local copy of `uv` rather than failing or skipping provisioning.

#### Scenario: uv already present

- **WHEN** `uv` is on PATH at provisioning time
- **THEN** the script uses that `uv` and does not bootstrap a second copy

#### Scenario: uv bootstrapped when absent

- **WHEN** `uv` is not on PATH at provisioning time and the script is not in dry-run
- **THEN** the script installs `uv` from the official installer (`curl -LsSf https://astral.sh/uv/install.sh | sh`) into `$PLUGIN_ROOT/.uv`, and then references the resulting `uv` binary by absolute path

#### Scenario: uv bootstrap does not mutate the user environment

- **WHEN** the script bootstraps `uv`
- **THEN** it runs the installer with `INSTALLER_NO_MODIFY_PATH=1` and targets `$PLUGIN_ROOT/.uv`, so the user's shell rc files, PATH, and system locations are not modified

#### Scenario: Provision a private CPython 3.15

- **WHEN** `uv` is available (already present or just bootstrapped) and the script is not in dry-run
- **THEN** the script installs CPython 3.15 into `$PLUGIN_ROOT/.python` via `uv python install 3.15` and wires `statusLine.command` at the resolved 3.15 interpreter binary

#### Scenario: Fallback to a system interpreter only when uv cannot be obtained

- **WHEN** `uv` is neither present nor obtainable (the bootstrap genuinely fails)
- **THEN** the script wires a system Python ≥3.10 (avoiding 3.14, which starts slower) instead, and still succeeds

#### Scenario: Dry-run previews provisioning without downloading

- **WHEN** the script runs with `--dry-run` and would provision the interpreter
- **THEN** it prints what it would bootstrap/install/wire and downloads nothing (no `uv` installer fetch, no `uv python install`)

### Requirement: Uninstall removes plugin-local provisioning artifacts

The uninstall flow SHALL remove the plugin-local provisioning artifacts it created — both `$PLUGIN_ROOT/.python` and `$PLUGIN_ROOT/.uv` — on a best-effort basis, honouring `--dry-run`.

#### Scenario: Uninstall removes the private CPython directory

- **WHEN** uninstall runs and `$PLUGIN_ROOT/.python` exists
- **THEN** the script removes it (or, under `--dry-run`, reports that it would remove it)

#### Scenario: Uninstall removes the bootstrapped uv directory

- **WHEN** uninstall runs and `$PLUGIN_ROOT/.uv` exists
- **THEN** the script removes it (or, under `--dry-run`, reports that it would remove it)

#### Scenario: Uninstall needs no jq

- **WHEN** uninstall removes `statusLine` from `settings.json` and checks plugin presence
- **THEN** it performs all JSON reads/edits via the resolved Python interpreter and never shells `jq`
