## Why

Today the only way to wire YAS into Claude Code is a multi-step manual dance (`claude plugin marketplace add …`, `claude plugin install …`, then `claude -p "/yas:init"`), and the settings-wiring logic lives *inline* in the `init` skill's `SKILL.md`. That makes one-line `curl | bash` bootstrapping impossible and leaves the tricky discovery/atomic-write logic with no single home or regression test. We want a single committed script that both a human (`curl | bash`) and the `yas:init` skill can run, so the wiring logic has exactly one source of truth.

## What Changes

- **Add `ops/install.sh`** — one script, two modes:
  - **Full mode** (human, `curl … | bash`): ensure the marketplace is added, install-or-update the `yas` plugin, then wire `settings.json`. Orchestrates `claude plugin marketplace add` / `install` / `update` with explicit `--scope user`, branching on `jq` reads of `known_marketplaces.json` / `installed_plugins.json`.
  - **Wire-only mode** (the skill, auto-detected when `CLAUDE_PLUGIN_ROOT` is set): skip all plugin management, point `settings.json` at the renderer under that exact plugin root. No network, no nested `claude` calls.
- **Flags**: `--wire-only` / `--full` to override mode detection; `--dry-run` to print intended actions without shelling `claude` or touching `settings.json`; `--main` reserved as the explicit dev/edge selector. `set -uo pipefail`, per-mode preflight dependency checks (`claude`/`curl` only required in full mode), macOS+Linux portable.
- **Gut `init/SKILL.md`** — its `<workflow>` collapses to `bash "${CLAUDE_PLUGIN_ROOT}/ops/install.sh"`; `allowed-tools` narrows to `Bash`. **BREAKING** only in the sense that the skill's internal implementation moves; its observable behaviour (wire-only `statusLine.command` write) is preserved.
- **README**: add the `curl … | bash` one-liner as the primary install path, keeping the manual `claude plugin` + `/yas:init` flow as a documented alternative.
- **CI/tests**: add `shellcheck ops/install.sh` to CI; add a hermetic wire-only regression test (fresh `CLAUDE_CONFIG_DIR`/`CLAUDE_PLUGIN_ROOT`, fake renderer) asserting correct `statusLine.command`, backup creation, exact-match skip, legacy-file removal, and corrupt-write rollback.

## Capabilities

### New Capabilities
- `install-script`: the `ops/install.sh` contract — its two modes, mode-detection rules, full-mode plugin orchestration, the wire-only `settings.json` write semantics (discovery, backup, atomic write, validate/restore, legacy cleanup), flags, and preflight behaviour.

### Modified Capabilities
<!-- The `init` skill is not currently captured as a spec; its wiring behaviour is absorbed into the new install-script capability. No existing spec's requirements change. -->

## Impact

- **New file**: `ops/install.sh`.
- **Modified**: `.claude/skills/init/SKILL.md` (gutted to a single call), `README.md` (install section), `.github/workflows/ci.yml` (shellcheck step), test suite (new wire-only behavioural test), possibly `.claude-plugin/permissions-allow.json` (kept scoped to what the skill's wire-only call triggers).
- **Dependencies**: full mode requires `claude` CLI + `curl` on PATH; both modes require `jq` (already a skill dependency) and Python 3.10+ (already required by the renderer).
- **No change** to the renderer (`claude/yas/**`) or any runtime statusline behaviour.
