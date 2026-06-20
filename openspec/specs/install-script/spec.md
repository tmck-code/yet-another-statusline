## Purpose

Define the behaviour of `ops/install.sh`, the single source of truth for wiring YAS into Claude Code. It covers full vs wire-only modes, the curl-pipe bootstrap entrypoint, plugin orchestration, safe `settings.json` writes performed entirely through Python (no `jq`), private CPython provisioning via `uv` (bootstrapped when absent), per-mode preflight, dry-run, uninstall cleanup, and the `yas:init` skill's delegation to the script.

## Requirements

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

This entrypoint SHALL run full mode, installing the latest plugin version served by the marketplace using the latest installer on the branch. The script SHALL NOT perform any release-tag pinning or self-re-execution. When a readable terminal is available, the script MAY reopen its own standard input from `/dev/tty` once (via `exec < /dev/tty`) to drive the interactive flow; this SHALL NOT involve re-downloading or re-executing the script.

#### Scenario: curl bootstrap runs unattended in a non-interactive context

- **WHEN** a user pipes the branch copy of `ops/install.sh` to bash on a machine with no readable `/dev/tty` (or with `YAS_NO_TTY=1`)
- **THEN** the script completes the full flow without requiring interactive input and never blocks on a prompt

#### Scenario: curl bootstrap reopens the terminal when one is available

- **WHEN** a user pipes the branch copy of `ops/install.sh` to bash attached to a terminal and `YAS_NO_TTY` is unset
- **THEN** the script reopens standard input from `/dev/tty` once and runs the interactive flow without re-fetching or re-executing itself

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

### Requirement: Dry-run mode

The script SHALL support a `--dry-run` flag that prints the intended actions for the selected mode without shelling `claude` or modifying `settings.json`.

#### Scenario: Dry-run prints decisions only

- **WHEN** the script runs with `--dry-run`
- **THEN** it prints whether it would add the marketplace, install vs update the plugin, and wire settings, but performs none of those side effects

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

### Requirement: Private interpreter provisioning via uv

The script SHALL provision a private, plugin-local CPython under `$PLUGIN_ROOT/.python` using `uv`, and wire `statusLine.command` to that interpreter for the fastest statusline startup, without mutating the user's system Python, shell rc, or PATH. `uv` SHALL be the guaranteed provisioning engine: when `uv` is already on PATH the script SHALL use it; when `uv` is absent the script SHALL bootstrap a plugin-local copy of `uv` rather than failing or skipping provisioning. The provisioned CPython version SHALL be resolved as `${YAS_PYTHON:-3.13}` — i.e. the non-interactive default SHALL be the stable 3.13 rather than a prerelease — overridable per Decision (interactive prompt) and by the `YAS_PYTHON` environment variable.

#### Scenario: uv already present

- **WHEN** `uv` is on PATH at provisioning time
- **THEN** the script uses that `uv` and does not bootstrap a second copy

#### Scenario: uv bootstrapped when absent

- **WHEN** `uv` is not on PATH at provisioning time and the script is not in dry-run
- **THEN** the script installs `uv` from the official installer (`curl -LsSf https://astral.sh/uv/install.sh | sh`) into `$PLUGIN_ROOT/.uv`, and then references the resulting `uv` binary by absolute path

#### Scenario: uv bootstrap does not mutate the user environment

- **WHEN** the script bootstraps `uv`
- **THEN** it runs the installer with `INSTALLER_NO_MODIFY_PATH=1` and targets `$PLUGIN_ROOT/.uv`, so the user's shell rc files, PATH, and system locations are not modified

#### Scenario: Non-interactive default is the stable 3.13

- **WHEN** the script provisions a private CPython in a non-interactive context with `YAS_PYTHON` unset and the script is not in dry-run
- **THEN** it installs CPython 3.13 (not 3.15) into `$PLUGIN_ROOT/.python` via `uv python install 3.13` and wires `statusLine.command` at the resolved 3.13 interpreter binary

#### Scenario: YAS_PYTHON overrides the version in any mode

- **WHEN** the script provisions a private CPython with `YAS_PYTHON=3.15` set and the script is not in dry-run
- **THEN** it installs CPython 3.15 into `$PLUGIN_ROOT/.python` and wires `statusLine.command` at the resolved 3.15 interpreter binary, in interactive or non-interactive mode alike

#### Scenario: Fallback to a system interpreter only when uv cannot be obtained

- **WHEN** `uv` is neither present nor obtainable (the bootstrap genuinely fails)
- **THEN** the script wires a system Python ≥3.10 (avoiding 3.14, which starts slower) instead, and still succeeds

#### Scenario: Dry-run previews provisioning without downloading

- **WHEN** the script runs with `--dry-run` and would provision the interpreter
- **THEN** it prints what it would bootstrap/install/wire at the resolved version and downloads nothing (no `uv` installer fetch, no `uv python install`)

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

### Requirement: Skill delegates to the script

The `yas:init` skill SHALL delegate its wiring work to `ops/install.sh` rather than carrying an inline implementation, preserving its observable behaviour of writing a wire-only `statusLine.command`. The plugin SHALL additionally ship a `yas:config` skill that delegates reconfiguration to `ops/install.sh --reconfigure`.

#### Scenario: Init skill invokes the shipped script

- **WHEN** the `yas:init` skill runs
- **THEN** it invokes `bash "${CLAUDE_PLUGIN_ROOT}/ops/install.sh"`, which detects wire-only mode and writes `settings.json` against that plugin root

#### Scenario: Config skill invokes reconfigure

- **WHEN** the `yas:config` skill runs
- **THEN** it invokes `bash "${CLAUDE_PLUGIN_ROOT}/ops/install.sh" --reconfigure`, which re-runs the interactive wizard against that plugin root without performing marketplace or plugin install

### Requirement: TTY detection and interactivity gating

The script SHALL run interactively by default and SHALL fall back to a fully non-interactive flow when interactivity is unavailable or suppressed. The script SHALL be considered interactive only when `YAS_NO_TTY` is unset or not equal to `1` AND a readable `/dev/tty` exists. When not interactive, the script SHALL issue no prompts and SHALL never block waiting for input. This guarantees CI safety: the non-interactive flow's behaviour SHALL be identical to the prior script except for the provisioned Python version default.

#### Scenario: YAS_NO_TTY forces non-interactive

- **WHEN** the script runs with `YAS_NO_TTY=1`
- **THEN** it issues no interactive prompts, writes no `yas.toml`, and completes the selected mode non-interactively

#### Scenario: No terminal forces non-interactive

- **WHEN** the script runs with no readable `/dev/tty` available (e.g. CI, a detached process)
- **THEN** it issues no interactive prompts and never blocks on input

#### Scenario: Terminal present enables interactive flow

- **WHEN** the script runs with a readable `/dev/tty` and `YAS_NO_TTY` unset
- **THEN** it runs the interactive flow (logo, Python prompt, config wizard) by reading keystrokes from the terminal

### Requirement: Self-contained embedded logo and selector

The script SHALL be self-contained and SHALL NOT depend at runtime on any git-untracked repository asset (the logo file, `select.sh`, or `checkbox.sh`), because Claude Code plugin packaging ships only git-tracked files and a `curl | bash` run has no repository checkout. The logo SHALL be embedded as a heredoc inside the script, and a single-select menu function SHALL be embedded inside the script. The embedded selector SHALL read keystrokes from `/dev/tty`, SHALL be compatible with bash 3.2 (no associative arrays, no `${var,,}` lowercasing expansion, no `mapfile`), and SHALL support an optional preview callback invoked on each highlight change with the highlighted value. The embedded selector SHALL retain a CC BY 4.0 attribution comment crediting blurayne's `select.sh`.

#### Scenario: Logo renders without a logo file present

- **WHEN** the interactive flow starts and no `yas.dos_rebel.plain.txt` file exists on disk
- **THEN** the script prints the embedded logo from its heredoc

#### Scenario: Selector works on bash 3.2

- **WHEN** the embedded single-select runs under bash 3.2 (e.g. stock macOS bash)
- **THEN** it presents the options, moves the highlight with arrow keys read from `/dev/tty`, and returns the chosen value without using bash-4+ features

#### Scenario: Selector drives a live preview

- **WHEN** a single-select is configured with a preview callback and the highlight moves to a new option
- **THEN** the callback is invoked with the newly highlighted value so the caller can render a live sample beneath the menu

### Requirement: Interactive configuration wizard

When interactive, the script SHALL run a configuration wizard that prompts for the four user-facing options — glyph mode (`appearance.glyphs.mode`), labels (`layout.labels`), theme (`appearance.theme`), and token soft limit (`tokens.soft_limit`) — and SHALL render live samples for glyph mode and theme. The glyph-mode and theme prompts SHALL render the sample session by invoking the provisioned interpreter on the shipped `statusline_command.py` with the shipped `session-info-example.json` on stdin and the corresponding `YAS_GLYPH_MODE` / `YAS_THEME` set, under a fixed `COLUMNS`. The labels prompt SHALL default to enabled for new users. The soft-limit prompt SHALL offer a fixed preset menu (150000, 200000, 500000, 1000000) only, with no free-form numeric entry, and SHALL close with a pointer to the README / `yas.example.toml` for per-model and advanced configuration. Preview renders SHALL NOT pollute any real session's statusline output (the preview invocation SHALL isolate the renderer's output directory, e.g. by pointing `CLAUDE_CONFIG_DIR` at a throwaway directory).

#### Scenario: Live preview for glyph mode and theme

- **WHEN** the user highlights a glyph mode or a theme in the wizard after the interpreter has been provisioned
- **THEN** the script renders the example statusline using that value beneath the menu, at the fixed preview width

#### Scenario: Labels default on

- **WHEN** the labels prompt is shown to a user with no existing configuration
- **THEN** the default selection is "on"

#### Scenario: Soft limit is a preset menu

- **WHEN** the soft-limit prompt is shown
- **THEN** the user chooses from the fixed presets 150000 / 200000 / 500000 / 1000000 and is then pointed to the README for advanced and per-model configuration, with no free-form numeric entry offered

#### Scenario: Previews do not pollute real session output

- **WHEN** the wizard renders preview statuslines
- **THEN** any statusline payload the renderer writes lands in a throwaway directory and not under the user's real `$CLAUDE_CONFIG_DIR/statusline-output/`

### Requirement: Interactive yas.toml generation with keep and print choices

When interactive, the wizard SHALL generate `$CLAUDE_CONFIG_DIR/yas.toml` from a commented template populated with the four chosen values, and SHALL NOT attempt to merge or preserve an existing file's comments or keys. When a `yas.toml` already exists the script SHALL offer to keep it as-is (skipping the questions and the write) or to reconfigure. After the questions the script SHALL offer to overwrite the file or to print the generated content to standard output for manual copy/paste. In non-interactive mode the script SHALL NOT write `yas.toml` at all. A write SHALL be performed safely (atomic temp-then-move).

#### Scenario: Existing yas.toml offers keep vs reconfigure

- **WHEN** the wizard starts and `$CLAUDE_CONFIG_DIR/yas.toml` already exists
- **THEN** the script offers to keep it as-is (skipping all questions and any write) or to reconfigure it

#### Scenario: Overwrite vs print after the questions

- **WHEN** the wizard has collected the four choices
- **THEN** the script offers to overwrite `$CLAUDE_CONFIG_DIR/yas.toml` with the generated content or to print that content to standard output without writing the file

#### Scenario: Generated toml carries the four chosen values

- **WHEN** the wizard generates `yas.toml`
- **THEN** the content sets `appearance.glyphs.mode`, `layout.labels`, `appearance.theme`, and `tokens.soft_limit` to the chosen values within the commented template

#### Scenario: Non-interactive writes no yas.toml

- **WHEN** the script runs non-interactively (CI, `YAS_NO_TTY=1`, or no `/dev/tty`)
- **THEN** it writes no `yas.toml` and relies on environment variables and built-in defaults

### Requirement: Reconfigure mode

The script SHALL support a `--reconfigure` flag that re-runs the interactive logo, Python-version prompt, configuration wizard, `yas.toml` write, and settings re-wire against the already-installed plugin, while skipping marketplace registration and plugin install/update. It SHALL reuse the existing plugin root via `CLAUDE_PLUGIN_ROOT` or the same renderer-discovery used by wiring. The post-install message of the install flow SHALL point users to `/yas:config` for later reconfiguration, including switching to Python 3.15.

#### Scenario: Reconfigure skips plugin management

- **WHEN** the script runs with `--reconfigure`
- **THEN** it re-runs the wizard and re-wires settings but does not add the marketplace or install/update the plugin

#### Scenario: Reconfigure reuses the existing plugin root

- **WHEN** `--reconfigure` runs with `CLAUDE_PLUGIN_ROOT` set or with the plugin discoverable on disk
- **THEN** it provisions/wires against that existing plugin root without reinstalling the plugin

#### Scenario: Post-install message points to the config skill

- **WHEN** the install flow completes
- **THEN** it prints guidance that `/yas:config` re-runs the wizard, noting it as the way to switch to Python 3.15 later
