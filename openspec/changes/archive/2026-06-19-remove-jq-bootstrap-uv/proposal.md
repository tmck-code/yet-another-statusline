## Why

`ops/install.sh` hard-depends on `jq` for all nine settings.json reads/transforms/validations, yet the installer's whole job is wiring a *Python* statusline command — it already requires (and now provisions) a Python interpreter, so `jq` is a redundant second dependency that machines (notably the stock `ghcr.io/tmck-code/claude-container:python` image) routinely lack. Separately, the new `provision_python` path gates the speed win behind `uv` being pre-installed, and preflight rejects a machine that has `uv` but no system Python even though that machine can be fully provisioned — so the installer fails on environments it could actually serve.

## What Changes

- **Remove the `jq` dependency entirely.** Route every JSON read/transform/validate through the Python interpreter the script already resolves, via a single injection-safe `json_py()` bash helper (heredoc Python script, file paths and values passed as **argv**, never string-interpolated). Convert all nine `jq` call-sites (`ensure_marketplace`, `ensure_plugin`, `do_wire` discovery + merge + validate + exact-match, `do_uninstall` has-key + del + discovery + present-check). Keep the mktemp/backup/validate/restore atomic-write flow byte-for-byte — only the JSON-producing command changes. **BREAKING** for the dependency contract: `jq` is no longer required or checked in either mode.
- **Bootstrap `uv` when absent.** `provision_python` grows a bootstrap step: if `command -v uv` succeeds, use it; otherwise fetch the official installer (`curl -LsSf https://astral.sh/uv/install.sh | sh`) with `INSTALLER_NO_MODIFY_PATH=1` and the install target pointed at `$PLUGIN_ROOT/.uv` (plugin-local, no shell-rc / PATH / system mutation), then reference the resolved `uv` binary by absolute path. `uv` thus becomes the guaranteed engine for `uv python install 3.15` → `$PLUGIN_ROOT/.python`. Honour `DRY_RUN` (preview, no download) in the new path.
- **Relax preflight.** The up-front gate becomes "a system Python ≥3.10 is present" (the bootstrap substrate), not "uv present". This closes a latent gap where preflight gated on `find_python` while `do_wire` prefers `provision_python`, wrongly rejecting uv-but-no-system-python machines. Wiring fallback order: prefer uv→3.15; only if uv genuinely cannot be obtained, wire a system Python ≥3.10 (still avoiding 3.14).
- **Uninstall symmetry.** `do_uninstall` also removes `$PLUGIN_ROOT/.uv` (best-effort, `DRY_RUN`-aware), mirroring the existing `.python` cleanup.
- **Verification harness.** Rework `ops/install-docker-test/` to run the local-branch `install.sh` against the **stock** `ghcr.io/tmck-code/claude-container:python` image (no Dockerfile needed once `jq` is gone), with a read-only repo mount and isolated `CLAUDE_PLUGIN_ROOT` / `CLAUDE_CONFIG_DIR`. Three scenarios: S1 uv-present, S2 uv-hidden (bootstraps uv), S3 uninstall removes `.python` and `.uv`.

## Capabilities

### New Capabilities
<!-- None — this change modifies the existing install-script capability. -->

### Modified Capabilities
- `install-script`: drops `jq` from the dependency/preflight contract (JSON handled via the resolved Python); makes `uv` a bootstrappable engine (installed plugin-locally under `$PLUGIN_ROOT/.uv` when absent) rather than a hard precondition for the speed win; relaxes preflight to require a system Python ≥3.10 substrate instead of `uv`; and extends uninstall to remove the plugin-local `.uv` alongside `.python`.

## Impact

- **Modified**: `ops/install.sh` (new `json_py()` helper; 9 jq → json_py conversions; `provision_python` uv bootstrap; `preflight_full` / `preflight_wire_only` relaxation; `do_uninstall` `.uv` cleanup).
- **Modified**: `openspec/specs/install-script/spec.md` (dependency, preflight, provisioning, uninstall requirements).
- **Modified**: `test/test_install_script.py` (drop the `jq`-present guard from full-dry tests; add a no-jq wire-only assertion; add uv-bootstrap coverage where hermetically feasible).
- **Modified/Replaced**: `ops/install-docker-test/` (`run.sh`, `container-test.sh`, removal of the `Dockerfile` — stock image once jq is gone), three scenarios S1–S3.
- **Dependencies**: `jq` removed entirely. Full mode now requires `claude` + `curl` + a system Python ≥3.10. Wire-only requires a system Python ≥3.10. `uv` is auto-bootstrapped via `curl` when absent.
- **No change** to the renderer (`claude/yas/**`) or any runtime statusline behaviour.
