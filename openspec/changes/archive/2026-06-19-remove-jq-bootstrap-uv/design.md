## Context

`ops/install.sh` (NOT repo root) currently depends on `jq` for every JSON read/transform/validate. There are nine `jq` call-sites:

- `ensure_marketplace` — `jq -r 'has("yet-another-statusline")'` on `known_marketplaces.json` (~line 163).
- `ensure_plugin` — `jq -r '.plugins | has("yas@yet-another-statusline")'` on `installed_plugins.json` (~line 187).
- `do_wire` discovery — the `.plugins | to_entries[] | … | .installPath` query on `installed_plugins.json` (~lines 231–238).
- `do_wire` exact-match — `jq -r '.statusLine.command // ""'` on `settings.json` (~line 288).
- `do_wire` merge — `jq --arg cmd … '.statusLine = {…}'` (~lines 312–313).
- `do_wire` validate — `jq empty "$SETTINGS"` (~line 323).
- `do_uninstall` has-key — `jq 'has("statusLine")'` (~line 359).
- `do_uninstall` del — `jq 'del(.statusLine)'` (~line 371).
- `do_uninstall` validate — `jq empty "$SETTINGS"` (~line 380).
- `do_uninstall` discovery + present-check — the same `.installPath` query (~line 396) and `jq -r '.plugins | has(...)'` (~line 425).

`preflight_full` (~line 131) requires `{claude, curl, jq}` then `find_python`. `preflight_wire_only` (~line 144) requires `jq` then `find_python`. `do_uninstall` separately re-checks `jq` (~line 342).

On this branch the script already gained `provision_python PLUGIN_ROOT` (~line 75) — it returns non-zero when `uv` is absent, installs CPython 3.15 into `$PLUGIN_ROOT/.python` via `UV_PYTHON_INSTALL_DIR=… uv python install 3.15`, and resolves the concrete binary via `uv python find 3.15 --managed-python` with a `find`-glob fallback. `find_python` (~line 109) picks a system interpreter ≥3.10, treating 3.14 as a last resort (3.14 starts slower than 3.13/3.15). `do_wire` (~line 277) prefers `provision_python`, falling back to `find_python`. `do_uninstall` (~lines 389–419) already removes `$PLUGIN_ROOT/.python` best-effort, `DRY_RUN`-aware.

The atomic settings write (mktemp → write → `mv` → validate → restore-from-backup) is correct and load-bearing; this change must preserve it exactly and swap only the JSON-producing command.

Tests live in `test/test_install_script.py` (hermetic). The full-dry tests are guarded by `requires_full_preflight`, which skips when any of `claude`/`curl`/`jq` is missing from PATH (lines ~132–140). A prototype wire-only Docker harness already exists at `ops/install-docker-test/` (`run.sh`, `container-test.sh`, `Dockerfile`) — treat it as throwaway reference.

## Goals / Non-Goals

**Goals:**
- Remove `jq` as a dependency of `ops/install.sh` entirely, routing all JSON through the Python interpreter the script already resolves.
- Make `uv` a guaranteed provisioning engine: bootstrap it plugin-locally when absent, without touching the user's shell rc / PATH / system.
- Relax preflight to gate on a system Python ≥3.10 substrate (not `uv`, not `jq`), fixing the uv-but-no-system-python rejection gap.
- Keep the atomic backup/validate/restore write semantics byte-for-byte.
- Extend uninstall to remove `$PLUGIN_ROOT/.uv` alongside `$PLUGIN_ROOT/.python`.
- Prove the local-branch code end-to-end via a Docker harness (S1 uv-present, S2 uv-hidden→bootstrap, S3 uninstall) against the **stock** container image.

**Non-Goals:**
- Replacing `uv`'s own provisioning behaviour or pinning the CPython 3.15 build (see the prerelease caveat below).
- Changing renderer code (`claude/yas/**`) or runtime statusline behaviour.
- Changing the full-mode marketplace/plugin orchestration (CLI calls, `--scope user`, dry-run decisions) beyond swapping `jq` reads for `json_py`.
- Adding a non-`uv` CPython download path (system Python ≥3.10 remains the only fallback when uv cannot be obtained).
- Vendoring or pinning a specific `uv` version in the bootstrap (the official installer serves the latest, matching the "branch serves latest installer" posture of the existing curl entrypoint).

## Decisions

### 1. One `json_py()` helper, values passed as argv (injection-safe)

Add a single bash helper `json_py(op, ...args)` that pipes a small Python heredoc to the resolved interpreter (`"$PYTHON_BIN"`, or a preflight-resolved system python for the marketplace/plugin reads that run before `do_wire` selects an interpreter). The heredoc reads `sys.argv` for the op selector, file paths, and any values — **never** string-interpolates them into the Python source. This is the injection-safe rule: a `settings.json` path or a command string containing quotes/backslashes/`$()` cannot corrupt the JSON or inject code, because it arrives as `sys.argv[n]`, not as concatenated source.

Sub-ops the nine call-sites need:
- `get-key FILE KEY` → print value of a top-level/dotted key, empty string if absent (replaces `jq -r '.statusLine.command // ""'` and the `has(...)` reads framed as a boolean op).
- `has-key FILE KEY` → print `true`/`false` (replaces `jq 'has("statusLine")'`, `jq -r 'has("yet-another-statusline")'`, `jq -r '.plugins | has("yas@yet-another-statusline")'`).
- `installpaths FILE` → print, one per line, the `installPath` of every `.plugins` entry whose key (ascii-lower) contains `yas` (replaces the `to_entries[] | select(... contains("yas")) | .value[] | .installPath` discovery query). The existing bash `while read | sort -Vr | head -1` post-filter (checks `statusline_command.py` / `.python` on disk) stays.
- `set-statusline FILE CMD` → load JSON (or `{}`), set `.statusLine = {"async":true,"command":CMD,"refreshInterval":1,"type":"command","padding":1}`, print the serialized result to stdout (replaces the `jq --arg cmd … '.statusLine = {…}'` merge; the bash side still writes stdout to the mktemp temp file and atomic-renames).
- `del-key FILE KEY` → load JSON, `pop` the key, print serialized result (replaces `jq 'del(.statusLine)'`).
- `validate FILE` → exit 0 iff `json.load` succeeds, non-zero otherwise (replaces `jq empty`). Implemented as `try: json.load(open(path)) except Exception: sys.exit(1)`.

Each Python op reads its target file defensively: missing/unparseable input degrades to "absent" / `{}` for read ops (mirroring the existing `2>/dev/null || present="false"` degradation), and only the explicit `validate` op signals corruption. The bash callers keep their existing `|| fallback` guards so behaviour on parse failure is unchanged.

### 2. Resolve a Python for the pre-wire reads

`ensure_marketplace` and `ensure_plugin` (and the uninstall present-check) run before `do_wire` selects `PYTHON_BIN`. They need *a* Python to call `json_py`. Use `find_python` (the system ≥3.10 substrate that preflight now guarantees) for these early reads — they only parse small Claude-managed JSON, so the private 3.15 isn't needed. Resolve it once near the top of each mode path (or lazily inside `json_py` defaulting to `find_python` when `PYTHON_BIN` is unset). The wiring reads/writes inside `do_wire` use the already-selected `PYTHON_BIN` (private 3.15 or system fallback) — either works; both are ≥3.10 and parse JSON identically.

### 3. uv bootstrap in `provision_python`, plugin-local, no system mutation

`provision_python` currently `return 1`s immediately when `uv` is absent. Replace that early return with a bootstrap step:
- If `command -v uv` succeeds → use that `uv` (current behaviour).
- Else, under `DRY_RUN`, print "Would bootstrap uv → `$PLUGIN_ROOT/.uv`" and continue the dry-run preview (no download).
- Else fetch and run the official installer: `curl -LsSf https://astral.sh/uv/install.sh | sh`, exported with `INSTALLER_NO_MODIFY_PATH=1` (skip shell-rc/PATH edits) and `UV_INSTALL_DIR="$PLUGIN_ROOT/.uv"` (the official installer honours `UV_INSTALL_DIR` for the binary destination). The resolved binary is then `$PLUGIN_ROOT/.uv/uv`; reference it by absolute path everywhere `uv` is currently called inside `provision_python` (the `uv python install` and `uv python find` invocations). Verify it is executable after bootstrap; if the bootstrap fails, `return 1` so `do_wire` falls back to `find_python`.

Concrete: introduce a local `UV_BIN` resolved to either `$(command -v uv)` or `$PLUGIN_ROOT/.uv/uv`, and call `"$UV_BIN"` rather than bare `uv` for the rest of the function. The `UV_PYTHON_INSTALL_DIR="$pydir"` scoping of `uv python install 3.15` and `uv python find` is unchanged.

### 4. Preflight gates on system Python ≥3.10, not uv, not jq

Drop `jq` from `preflight_full`'s tool loop (leave `claude`, `curl`). Delete the `jq` check from `preflight_wire_only` and the standalone `jq` re-check in `do_uninstall`. Both preflights keep their `find_python > /dev/null || exit 1` gate — that system ≥3.10 interpreter is exactly the substrate the uv bootstrap (and the `json_py` reads) run on. This closes the latent gap: today preflight gates on `find_python` while `do_wire` prefers `provision_python`, so the gate and the actual wiring engine disagree; after this change the gate guarantees the substrate both the bootstrap and the JSON helper require, and uv is no longer demanded up-front because it can be installed.

### 5. Uninstall also removes `$PLUGIN_ROOT/.uv`

Mirror the existing `.python` cleanup block in `do_uninstall`: after (or alongside) removing `$(yas_python_dir "$UN_ROOT")`, remove `$UN_ROOT/.uv` if present, `DRY_RUN`-aware ("Would remove bootstrapped uv dir …" vs `rm -rf`). Reuse the same `UN_ROOT` discovery (env `CLAUDE_PLUGIN_ROOT` if its `.python`/`.uv` exists, else the `installpaths` `json_py` scan). Consider a small `yas_uv_dir() { printf '%s/.uv\n' "$1"; }` helper symmetric with `yas_python_dir`.

### 6. Docker harness against the stock image, three scenarios

Once `jq` is gone, the harness no longer needs a Dockerfile that apt-installs `jq` — it can run the stock `ghcr.io/tmck-code/claude-container:python` image directly (it ships bash/curl/git/claude/uv and a non-root `claude` user; it has no system `python3`, which exercises provisioning). Rework `ops/install-docker-test/`:
- **Delete the `Dockerfile`** (no jq augmentation needed) and have `run.sh` `docker run` the stock image with `-v "$REPO_ROOT":/repo:ro` and an isolated `CLAUDE_PLUGIN_ROOT` / `CLAUDE_CONFIG_DIR` under a writable stage dir (the existing `container-test.sh` already copies `/repo` → a writable `/app/work` because the mount is read-only).
- **S1 (uv present):** run `install.sh --wire-only`; assert it provisions 3.15 under `.python`, wires the command, renders `ops/session-info-example.json` non-empty, settings shape is correct. (This is the current A1–A3, minus the jq dependency in the assertions — switch the harness's own `jq` reads to a python one-liner so the container needs no jq either.)
- **S2 (uv hidden):** run with `PATH=/uv/.venv/bin:/usr/bin:/bin` (or otherwise hide the stock `uv`) so `command -v uv` fails; assert the script **bootstraps uv** into `$CLAUDE_PLUGIN_ROOT/.uv`, then provisions 3.15 and wires. Confirm `$CLAUDE_PLUGIN_ROOT/.uv/uv` exists and is executable.
- **S3 (uninstall):** run `install.sh --uninstall`; assert `.statusLine` is stripped AND both `$CLAUDE_PLUGIN_ROOT/.python` and `$CLAUDE_PLUGIN_ROOT/.uv` are gone. (Extends the current A4 to also check `.uv`.)

This is a verification vehicle, not a unit test — tasks.md tracks it but it is exercised manually / in CI, not in `pytest`.

## Risks / Trade-offs

- **`uv python install 3.15` resolves to a 3.15 *prerelease*.** 3.15 is not yet stable, so `uv` currently installs a prerelease CPython 3.15. This is an accepted trade-off: the startup win (~6–8 ms faster than 3.13; 3.14 is slower) outweighs running a prerelease for the short-lived statusline subprocess, which executes a small, well-exercised renderer. **Future work:** repin / re-verify when CPython 3.15 ships stable. Documented here so it is a known, deliberate caveat rather than a surprise.
- **uv bootstrap adds a network fetch on machines without uv.** The official installer download is one-time and plugin-local; subsequent runs reuse `$PLUGIN_ROOT/.uv/uv`. `--dry-run` previews it without downloading. Bootstrap failure degrades cleanly to the system-Python fallback (no hard failure).
- **Trusting `astral.sh/uv/install.sh`.** The bootstrap pipes a remote installer to `sh` — the same trust-on-first-use posture the existing curl entrypoint already takes. Constrained with `INSTALLER_NO_MODIFY_PATH=1` and a plugin-local `UV_INSTALL_DIR` so it cannot mutate the user's shell rc, PATH, or system locations.
- **`json_py` heredoc must stay injection-safe.** The whole point of argv-passing is defeated if any future edit interpolates a path/value into the heredoc body. The spec encodes this as a normative scenario; reviewers should treat any `$var` inside the Python source (vs `sys.argv`) as a defect.
- **Two interpreters in play (system substrate for early reads, private 3.15 for wiring).** Both are ≥3.10 and parse JSON identically; the split exists only because the marketplace/plugin reads run before `do_wire` selects the private interpreter. Keeping the early reads on `find_python` avoids provisioning 3.15 just to read `known_marketplaces.json`.

## Open Questions (resolved empirically against `ghcr.io/tmck-code/claude-container:python`)

- **Exact `uv` binary path after a custom-dir bootstrap — RESOLVED.** Running `INSTALLER_NO_MODIFY_PATH=1 UV_INSTALL_DIR=$PLUGIN_ROOT/.uv curl -LsSf https://astral.sh/uv/install.sh | sh` installs **flat**: the binary lands at `$PLUGIN_ROOT/.uv/uv` (plus `$PLUGIN_ROOT/.uv/uvx`), no `bin/` nesting. So `UV_BIN="$plugin_root/.uv/uv"` is correct; keep the `find … -name uv` glob only as defensive fallback.
- **S2 PATH-hiding technique — RESOLVED, original assumption was WRONG.** `uv` exists at **two** on-disk locations in the image: `/usr/local/bin/uv` and `/uv/.venv/bin/uv`. The latter is **co-located with `python`** (`/uv/.venv/bin/python`, version **3.14.6** — the only system interpreter), so the assumed `PATH=/uv/.venv/bin:/usr/bin:/bin` would NOT hide uv. Correct S2 hide: create a curated dir (e.g. `/app/pybin`) with a `python`/`python3` symlink to `/uv/.venv/bin/python`, then run with `PATH=/app/pybin:/usr/bin:/bin` — this excludes both uv dirs (uv is absent from `/usr/bin` and `/bin`) while keeping `python` (substrate, 3.14.6 → `find_python` last-resort) and `curl` (in `/usr/bin`, for the bootstrap). `command -v uv` then genuinely fails, exercising the bootstrap path.
