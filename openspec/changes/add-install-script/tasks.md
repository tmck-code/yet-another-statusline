## 1. Preflight verification

- [ ] 1.1 Verify whether `claude plugin install` / `claude plugin marketplace add` run non-interactively under a piped (non-TTY) stdin; record the finding and decide if a `/dev/tty` redirect or non-interactive flag is needed (resolves the design's Open Question)

## 2. Write `ops/install.sh`

- [ ] 2.1 Create `ops/install.sh` with `#!/usr/bin/env bash`, `set -uo pipefail`, executable bit, and the skill's two-space `printf` / `!`-prefixed output style
- [ ] 2.2 Implement arg/env parsing and mode dispatch: `CLAUDE_PLUGIN_ROOT` set ⇒ wire-only; unset ⇒ full; `--wire-only` / `--full` / `--dry-run` / `--main` overrides
- [ ] 2.3 Implement per-mode preflight dependency checks (full: `claude` + `curl` + `jq`; wire-only: `jq` + Python 3.10+), erroring with install hints and non-zero exit on missing deps
- [ ] 2.4 Implement `ensure_marketplace` (full only): jq-read `known_marketplaces.json`, `claude plugin marketplace add tmck-code/yet-another-statusline` only if the `yet-another-statusline` key is absent
- [ ] 2.5 Implement `ensure_plugin` (full only): jq-read `installed_plugins.json`, `claude plugin install … --scope user` if `yas@yet-another-statusline` absent else `claude plugin update … --scope user`
- [ ] 2.6 Implement `do_wire`: port the skill's wiring logic — renderer discovery (prefer `CLAUDE_PLUGIN_ROOT` in wire-only, else version-sorted `installed_plugins.json` then cache-scan fallback), legacy `statusline-info-*` cleanup, Python 3.10+ detection, exact-match skip, backup → atomic temp-write + rename → JSON-validate → restore-on-corruption
- [ ] 2.7 Wire `--dry-run` through every side-effecting step so it prints intended actions (would add/install/update/wire) without shelling `claude` or touching `settings.json`
- [ ] 2.8 Guard jq reads with `2>/dev/null` so a schema/parse failure degrades to "treat as absent" rather than crashing

## 3. Gut the skill

- [ ] 3.1 Replace `init/SKILL.md` `<workflow>` with a single `bash "${CLAUDE_PLUGIN_ROOT}/ops/install.sh"` call and a one-line objective
- [ ] 3.2 Narrow `allowed-tools` to `Bash`; update `.claude-plugin/permissions-allow.json` to stay scoped to what the wire-only call triggers
- [ ] 3.3 Manually run the skill path (`CLAUDE_PLUGIN_ROOT` set) and confirm `settings.json` is wired identically to the old inline behaviour

## 4. Tests & CI

- [ ] 4.1 Add a hermetic wire-only test (fresh `CLAUDE_CONFIG_DIR` + `CLAUDE_PLUGIN_ROOT`, fake `claude/statusline_command.py`) asserting: correct `statusLine.command`, `.bak` created, exact-match skip, legacy-file removal, corrupt-write rollback
- [ ] 4.2 Add `--dry-run` assertions exercising full-mode decision logic (would-add vs skip marketplace, install vs update) without network/`claude`
- [ ] 4.3 Add a `shellcheck ops/install.sh` step to `.github/workflows/ci.yml`
- [ ] 4.4 Run `make test` and `shellcheck` locally; confirm green

## 5. Docs

- [ ] 5.1 Update `README.md` Install/Update: add the `curl -fsSL …/main/ops/install.sh | bash` one-liner as the primary path, keeping the manual `claude plugin` + `/yas:init` flow as a documented alternative
- [ ] 5.2 Confirm the README raw URL uses the `main` branch (not `master`)
