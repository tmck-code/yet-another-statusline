## Context

The `yas:init` skill (`.claude/skills/init/SKILL.md`) carries ~100 lines of inline bash that locates the newest installed plugin renderer, cleans legacy files, detects Python 3.10+, and atomically writes `statusLine.command` into `settings.json` with a backup/validate/restore safety net. There is no committed `.sh` in the repo and no `curl | bash` install path — humans must run `claude plugin marketplace add`, `claude plugin install`, then `claude -p "/yas:init"` by hand. We want one script that humans and the skill both run, with the wiring logic in exactly one place and a regression test guarding the file-munging half.

The plugin CLI surface is fixed: `claude plugin marketplace add <repo>`, `claude plugin install <plugin> --scope user`, `claude plugin update <plugin> --scope user`. On-disk state is inspectable: marketplace presence in `$CLAUDE_CONFIG_DIR/plugins/known_marketplaces.json` (key `yet-another-statusline`), plugin presence in `installed_plugins.json` (key `yas@yet-another-statusline`). The skill already depends on reading `installed_plugins.json`, so coupling to that schema is pre-existing, not new.

## Goals / Non-Goals

**Goals:**
- One committed `ops/install.sh` as the single source of truth for settings-wiring.
- A `curl … | bash` entrypoint that bootstraps a fresh machine end-to-end.
- The `yas:init` skill reduced to a single delegating call, with identical observable behaviour.
- A hermetic regression test for the wire-only path (where a bug actually corrupts a user's `settings.json`).

**Non-Goals:**
- Release-tag pinning or self-re-execution of the installer (explicitly dropped — the branch serves the latest installer, the marketplace serves the latest plugin).
- Pinning the installed plugin *code* to a tag (the plugin CLI owns ref resolution).
- A standalone code-distribution path that bypasses the plugin/marketplace system (the script orchestrates the CLI, it does not clone the repo).
- Auto-restart of Claude Code (empirically the statusline reflects the new `settings.json` immediately; no restart nag).
- Behavioural test coverage of full-mode CLI orchestration beyond `--dry-run` decision assertions (real install needs network + `claude`).

## Decisions

### One script, two modes, auto-detected by `CLAUDE_PLUGIN_ROOT`
The script dispatches on environment, not on the caller knowing a flag. `CLAUDE_PLUGIN_ROOT` is set when the skill invokes the script from inside the plugin and unset under `curl | bash`. Set ⇒ **wire-only** (skip marketplace/install/update, wire *that exact root*, no scan, no network, no nested `claude`). Unset ⇒ **full** (ensure marketplace → install/update → wire). Explicit `--wire-only` / `--full` override the detection for testability. *Alternative considered:* a mandatory flag — rejected because it forces caller knowledge and is easy to mis-call; *always-full* — rejected because it would trigger nested `claude` calls and surprise mid-session plugin updates every `/yas:init`.

### Inspect-then-act idempotency (jq on the JSON), not CLI-error tolerance
Full mode reads `known_marketplaces.json` / `installed_plugins.json` with `jq` to decide add-vs-skip and install-vs-update, giving honest progress output ("Adding marketplace…", "Installing…", "Updating…"). Guarded with `2>/dev/null`; a parse failure degrades to "treat as absent" (try to add/install) rather than crashing. *Alternative considered:* fire idempotent CLI commands and swallow failures — rejected as it depends on undocumented exit codes/error strings and can't cleanly distinguish install from update. The skill already couples to `installed_plugins.json`, so this adds no new coupling.

### The skill calls the local copy, not curl
`yas:init` runs `bash "${CLAUDE_PLUGIN_ROOT}/ops/install.sh"`. Because `claude plugin install` always pulls the latest marketplace version, the shipped `ops/install.sh` *is* the current installer — same file, same wire-only branch. Calling local avoids a network dependency and the supply-chain footgun of piping remote code to bash inside an automated agent session. "Same path" is satisfied by it being one file, not by the fetch mechanism. *Alternative considered:* skill curls the branch copy — rejected; it reintroduces un-vetted-`main` execution *inside* an unattended session for zero benefit (the wire-only guard fires either way).

### No installer pinning / no re-exec
Earlier exploration considered resolving the latest release tag via the GitHub API and re-fetching a pinned installer. Dropped per decision: the curl entrypoint always runs the branch copy (`…/main/ops/install.sh`), which installs the latest marketplace plugin. Simpler, no API rate-limit failure mode, no self-re-exec machinery. `--main` remains reserved as an explicit dev/edge selector but does not change the default branch-tracking behaviour.

### `--scope user` everywhere; `set -uo pipefail`; per-mode preflight
Install/update get explicit `--scope user` so plugin and `settings.json` land in the same scope. `set -uo pipefail` *without* `-e` — the presence probes branch on exit codes and `-e` would abort on the first "absent" result; genuinely fatal steps get explicit `|| { echo …; exit 1; }`. Preflight checks only what the mode needs: full mode requires `claude` + `curl` + `jq`; wire-only requires only `jq` + Python 3.10+. Output matches the skill's existing style (two-space `printf` progress lines, `!`-prefixed errors, no color). Portable across macOS + Linux using the same primitives the skill's proven block already uses (`date -u`, `mktemp`, `sort -Vr`, `find -maxdepth`).

### `--dry-run` for testable orchestration
A `--dry-run` flag prints the would-do decisions (add-marketplace? install-vs-update? wire?) without shelling `claude` or touching `settings.json`, making full-mode decision logic CI-exercisable and giving cautious users a preview.

## Risks / Trade-offs

- **GitHub default branch is `main`, not `master`** → the README one-liner and any raw URL must use `main`; a `master` URL would 404. Verified `origin/HEAD → origin/main`.
- **`claude plugin install` interactivity under a non-TTY pipe** → if it prompts, `curl | bash` would hang. Mitigation: verify non-interactivity against the installed CLI before finalizing; if it prompts, document reading from `/dev/tty` or hunt a non-interactive flag. Must be confirmed, not assumed.
- **Coupling to `known_marketplaces.json` / `installed_plugins.json` schema (`version: 2`)** → Anthropic could change it. Mitigation: `2>/dev/null`-guarded reads that degrade to "absent" so a schema change yields "try to add/install" rather than a crash. Pre-existing coupling for the plugin half.
- **Gutting `SKILL.md` removes the only existing copy of the wiring logic** → all wiring safety now lives in one script. Mitigation: the hermetic wire-only regression test (backup, exact-match skip, legacy cleanup, corrupt-write rollback) plus `shellcheck` in CI.
- **`curl | bash` is inherently trust-on-first-use** → mitigated by also documenting the manual `claude plugin` + `/yas:init` path for users who won't pipe remote code to a shell.

## Migration Plan

1. Add `ops/install.sh` (full + wire-only) and make it executable.
2. Verify `claude plugin install` non-interactivity; adjust the script if it prompts.
3. Gut `init/SKILL.md` to the single delegating call; narrow `allowed-tools` to `Bash`; keep `permissions-allow.json` scoped to the wire-only call's commands.
4. Update `README.md` install section (curl primary, manual alternative).
5. Add `shellcheck ops/install.sh` to `ci.yml` and the hermetic wire-only test.
6. Rollback is trivial: the change is additive plus a skill edit; reverting the `SKILL.md` edit restores the inline implementation.

## Open Questions

- Confirm whether `claude plugin install` / `marketplace add` run non-interactively under a piped stdin, or require a `/dev/tty` redirect or a yet-unknown flag. To be answered against the CLI during implementation, not by assumption.
