## 1. Add the `json_py()` helper in `ops/install.sh`

- [x] 1.1 Add a `json_py OP [ARGS...]` bash function near the top of `ops/install.sh` (after the `CLAUDE_CONFIG_DIR` setup, before the provisioning block). It pipes a single-quoted Python heredoc to a resolved interpreter and passes the op selector, file paths, and values **as argv** (`"$@"` → `sys.argv`), never interpolated into the heredoc body. Resolve the interpreter as: use a caller-provided `$PYTHON_BIN` if set, else `find_python` (the system ≥3.10 substrate). Injection-safety is a hard requirement — no `$var` may appear inside the Python source.
- [x] 1.2 Implement sub-op `get-key FILE KEY`: load JSON (or `{}` on missing/unparseable), print the value at top-level `KEY` as a string, empty string if absent. Replaces `jq -r '.statusLine.command // ""'`.
- [x] 1.3 Implement sub-op `has-key FILE KEY`: print `true`/`false` for top-level key presence. Supports a dotted form for `.plugins | has("yas@…")` (e.g. accept `plugins.yas@yet-another-statusline` or a two-arg `PARENT CHILD`). Replaces the three `has(...)` reads (`ensure_marketplace` ~163, `ensure_plugin` ~187, `do_uninstall` ~359 and ~425).
- [x] 1.4 Implement sub-op `installpaths FILE`: print, one per line, the `installPath` of every `.plugins` entry whose key (ascii-lower) contains `yas`. Replaces the `to_entries[] | select(... contains("yas")) | .value[] | .installPath` discovery (`do_wire` ~231, `do_uninstall` ~396). The existing bash `while read | … | sort -Vr | head -1` on-disk post-filter stays.
- [x] 1.5 Implement sub-op `set-statusline FILE CMD`: load JSON (or `{}`), set `.statusLine = {"async":true,"command":CMD,"refreshInterval":1,"type":"command","padding":1}`, print the serialized JSON to stdout. Replaces the `jq --arg cmd … '.statusLine = {…}'` merge (~312–313). The bash caller still writes stdout to the mktemp temp file and atomic-renames.
- [x] 1.6 Implement sub-op `del-key FILE KEY`: load JSON, remove top-level `KEY`, print serialized JSON to stdout. Replaces `jq 'del(.statusLine)'` (~371).
- [x] 1.7 Implement sub-op `validate FILE`: `exit 0` iff `json.load(open(FILE))` succeeds, non-zero otherwise. Replaces `jq empty` (~323, ~380).

## 2. Convert the nine jq call-sites to `json_py`

- [x] 2.1 `ensure_marketplace` (~163): `present=$(json_py has-key "$CLAUDE_CONFIG_DIR/plugins/known_marketplaces.json" yet-another-statusline)`, keeping the `|| present="false"` degradation.
- [x] 2.2 `ensure_plugin` (~187): `present=$(json_py has-key "…/installed_plugins.json" plugins yas@yet-another-statusline)`, keeping the degradation.
- [x] 2.3 `do_wire` discovery (~231–242): replace the `jq` query with `json_py installpaths "…/installed_plugins.json"`, leaving the `while IFS= read -r d; … | sort -Vr | head -1` post-filter unchanged.
- [x] 2.4 `do_wire` exact-match (~288): `OLD_CMD=$(json_py get-key "$SETTINGS" statusLine.command)` (support the dotted `statusLine.command` read in `get-key`, or read `statusLine` then `.command` — pick one and keep it consistent), keeping `|| printf ''`.
- [x] 2.5 `do_wire` merge (~311–316): `_result=$(json_py set-statusline "$SETTINGS" "$NEW_CMD")`, keeping the `|| [ -z "$_result" ]` failure guard and the existing mktemp → `mv` atomic write that follows. Do NOT alter the backup/mktemp/restore flow.
- [x] 2.6 `do_wire` validate (~323): `if ! json_py validate "$SETTINGS"; then … restore backup … fi`, unchanged restore semantics.
- [x] 2.7 `do_uninstall` has-key (~359): `HAS_KEY=$(json_py has-key "$SETTINGS" statusLine)`, keeping `|| HAS_KEY="false"`.
- [x] 2.8 `do_uninstall` del (~371): `_result=$(json_py del-key "$SETTINGS" statusLine)`, keeping the `|| [ -z "$_result" ]` guard and the existing mktemp atomic write.
- [x] 2.9 `do_uninstall` validate (~380): `if ! json_py validate "$SETTINGS"; then … restore backup … fi`.
- [x] 2.10 `do_uninstall` discovery + present-check (~396, ~425): `installpaths` for the `.python`/`.uv` root scan and `has-key … plugins yas@yet-another-statusline` for the plugin-present gate.
- [x] 2.11 Update the script's top-of-file mode/Requires comment block (~lines 4–10) to drop every `jq` mention.

## 3. uv bootstrap in `provision_python`

- [x] 3.1 In `provision_python` (~75) replace the early `command -v uv … || return 1` with engine resolution: set `local UV_BIN`; if `command -v uv` succeeds, `UV_BIN=$(command -v uv)`; else bootstrap (3.2). Reference `"$UV_BIN"` for every `uv` call in the function (the `uv python install 3.15` and `uv python find` lines), keeping the `UV_PYTHON_INSTALL_DIR="$pydir"` scoping.
- [x] 3.2 Bootstrap branch (uv absent, not dry-run): run `INSTALLER_NO_MODIFY_PATH=1 UV_INSTALL_DIR="$plugin_root/.uv" sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'` (or equivalent), then resolve `UV_BIN="$plugin_root/.uv/uv"`. Confirm the binary path against the live installer's layout; if it nests, fall back to a `find "$plugin_root/.uv" -name uv -type f -perm -u+x | head -1` glob (mirrors the existing 3.15 binary resolution). If `UV_BIN` is missing/not executable after bootstrap, `return 1` (→ `find_python` fallback).
- [x] 3.3 Dry-run path: when `DRY_RUN=1` and uv is absent, print `  Would bootstrap uv → $plugin_root/.uv` to stderr and continue emitting the synthetic `<cpython-3.15>` preview path (no download). When uv is present in dry-run, keep current behaviour. Ensure no network call happens under dry-run on either branch.
- [x] 3.4 Add a `yas_uv_dir() { printf '%s/.uv\n' "$1"; }` helper alongside `yas_python_dir` (~59) for symmetry, used by provisioning and uninstall.

## 4. Relax preflight

- [x] 4.1 `preflight_full` (~131): drop `jq` from the `for tool in claude curl jq` loop (leave `claude curl`); remove the `jq)` case arm. Keep the `find_python > /dev/null || exit 1` substrate gate.
- [x] 4.2 `preflight_wire_only` (~144): delete the `command -v jq … || exit 1` line; keep only the `find_python` gate.
- [x] 4.3 `do_uninstall` (~342): delete the standalone `command -v jq … || exit 1` re-check (JSON now goes through `json_py`).
- [x] 4.4 Confirm `do_wire`'s engine selection (~277) already encodes the intended order — prefer `provision_python` (uv→3.15, now bootstrappable), fall back to `find_python` (system ≥3.10, avoiding 3.14). Adjust only if needed so the relaxed preflight and wiring agree.

## 5. Uninstall removes `$PLUGIN_ROOT/.uv`

- [x] 5.1 In `do_uninstall`'s artifact-cleanup block (~389–419), after/alongside the `.python` removal, remove `$(yas_uv_dir "$UN_ROOT")` if present, `DRY_RUN`-aware (`  Would remove bootstrapped uv dir %s` vs `rm -rf … && printf …`). Reuse the existing `UN_ROOT` discovery (env `CLAUDE_PLUGIN_ROOT` if its `.python`/`.uv` exists, else the `installpaths` scan), extending the existence test to also match a `.uv` dir.

## 6. Spec

- [x] 6.1 Apply the delta in `openspec/changes/remove-jq-bootstrap-uv/specs/install-script/spec.md` to `openspec/specs/install-script/spec.md` at archive: the MODIFIED "Wire-only settings write" and "Per-mode preflight and strictness" requirements, plus the ADDED "Private interpreter provisioning via uv" and "Uninstall removes plugin-local provisioning artifacts" requirements. (Handled by `openspec archive`; verify the wording matches the shipped behaviour before archiving.)

## 7. Tests (`test/test_install_script.py`)

- [x] 7.1 Remove the `jq` member from the `requires_full_preflight` guard list (~133): change `('claude', 'curl', 'jq')` to `('claude', 'curl')` so full-dry tests no longer skip when `jq` is absent.
- [x] 7.2 Add a wire-only test that proves no jq dependency: run `install.sh` (wire-only) with `PATH` scrubbed of `jq` (e.g. a tmp PATH that contains bash/python/coreutils but not jq, or stub a failing `jq`) and assert `settings.json` is wired correctly and the run exits 0. Reuse the `wire_env` fixture.
- [x] 7.3 Add (where hermetically feasible) uv-bootstrap coverage: assert that with `uv` absent and `DRY_RUN` set, the dry-run output mentions bootstrapping uv → `.uv` and the run makes no network call / writes nothing. Full network-dependent provisioning (real `uv python install 3.15`) stays in the Docker harness, not pytest.
- [x] 7.4 Confirm the existing uninstall tests still pass; add an assertion (hermetic, dry-run) that uninstall reports it would remove the `.uv` dir when one exists under the plugin root.
- [x] 7.5 Run `make test` (or `uv run pytest -q test/test_install_script.py`) and `shellcheck ops/install.sh`; confirm green.

## 8. Docker verification harness (`ops/install-docker-test/`)

- [x] 8.1 Delete `ops/install-docker-test/Dockerfile` (no jq augmentation needed once jq is gone) and point `run.sh` at the stock `ghcr.io/tmck-code/claude-container:python` image directly (`docker run` it, dropping the `docker build` step), keeping `-v "$REPO_ROOT":/repo:ro`, the writable `/app/work` stage, and isolated `CLAUDE_PLUGIN_ROOT` / `CLAUDE_CONFIG_DIR`.
- [x] 8.2 Replace the harness's own internal `jq` reads in `container-test.sh` with a python one-liner (the container has no jq), so the harness proves a jq-free environment end-to-end.
- [x] 8.3 S1 (uv present): `install.sh --wire-only` → assert wired to a private uv-managed CPython 3.15 under `.python` (not bare system python, not 3.14), renders `ops/session-info-example.json` non-empty, settings shape correct (carry over A1–A3).
- [x] 8.4 S2 (uv hidden): re-run with the stock `uv` removed from PATH (confirm the actual `uv` location in the image first; resolves the design Open Question) so `command -v uv` fails → assert the script **bootstraps** `$CLAUDE_PLUGIN_ROOT/.uv/uv` (exists, executable), then provisions 3.15 and wires.
- [x] 8.5 S3 (uninstall): `install.sh --uninstall` → assert `.statusLine` stripped AND both `$CLAUDE_PLUGIN_ROOT/.python` and `$CLAUDE_PLUGIN_ROOT/.uv` removed (extend A4).
- [x] 8.6 Run `bash ops/install-docker-test/run.sh` and confirm S1–S3 all PASS.

## 9. Final verification

- [x] 9.1 `shellcheck ops/install.sh` clean; `make test` green; the Docker harness green. Confirm a grep for `\bjq\b` over `ops/install.sh` returns nothing.
