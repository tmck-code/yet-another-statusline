## 1. Arg parsing, mode selection, and TTY gating (`ops/install.sh`)

- [x] 1.1 Add `--reconfigure` to the `for arg in "$@"` case loop (around lines 34–46) with a `RECONFIGURE_FLAG=1`, alongside the existing `WIRE_ONLY_FLAG` / `FULL_FLAG` / `UNINSTALL_FLAG` / `DRY_RUN` / `--main` handling.
- [x] 1.2 In the mode-selection block (lines 49–54), add a `reconfigure` mode: `elif [ "$RECONFIGURE_FLAG" = "1" ]; then MODE="reconfigure"` ahead of the `CLAUDE_PLUGIN_ROOT` auto-detect branches.
- [x] 1.3 Add an `is_interactive()` predicate near the top (after `CLAUDE_CONFIG_DIR` is set, line 56): returns true only when `[ "${YAS_NO_TTY:-}" != "1" ]` AND `[ -r /dev/tty ]`. Set an `INTERACTIVE` flag once from it. The predicate MUST be safe under `set -u`.
- [x] 1.4 In the interactive branches only, run `exec < /dev/tty` exactly once before any prompt, so `curl | bash` (where fd 0 is the consumed pipe) reattaches to the terminal. Do NOT re-download or re-exec.

## 2. Embedded logo and bash-3.2-safe single-select (`ops/install.sh`)

- [x] 2.1 Add `print_logo()` that prints the 8-line, 42-col plain logo from `yas.dos_rebel.plain.txt` as a single-quoted heredoc (`<<'EOF'`). The heredoc is the source of truth — do NOT read the untracked file at runtime. Copy the exact glyph bytes from the dev file.
- [x] 2.2 Embed a minimal single-select function derived from blurayne's `select.sh`. Requirements: reads keystrokes from `/dev/tty` (arrow up/down + enter), returns the chosen index and value via a global (mirror the upstream `UI_WIDGET_RC` convention), is bash-3.2-safe (no associative arrays, no `${var,,}`, no `mapfile`), and accepts an **optional preview-callback name** invoked with the highlighted value on each highlight change.
- [x] 2.3 Preserve a verbatim **CC BY 4.0 attribution comment** crediting blurayne immediately above the embedded selector. Do NOT embed `checkbox.sh` (multi-select is a non-goal).
- [x] 2.4 Add a `prompt_yes_no(question, default)` helper (bash-3.2-safe, reads `/dev/tty`) for the Python and labels prompts; `default` selects the highlighted/empty-enter answer.

## 3. Python version policy (`provision_python` reads `VER`)

- [x] 3.1 Parameterise `provision_python` (lines 208–259) on a version: resolve `local VER="${YAS_PYTHON:-3.13}"` at function entry (or accept it as `$2` set by the caller). Replace EVERY hardcoded `3.15` token: the two dry-run `printf` lines (~239, ~241), `uv python install 3.15` (~247), `uv python find 3.15` (~251), and the fallback glob `-name python3.15 -path '*/cpython-3.15*/bin/*'` (~255) → `python$VER` / `cpython-$VER*`.
- [x] 3.2 Update the `do_wire` printf at line 423 (`(private uv-managed 3.15)`) to print the resolved `$VER` instead of a literal 3.15.
- [x] 3.3 Update the function header comment (lines 194–207) and the file-top comment about 3.15 provisioning to describe the `${YAS_PYTHON:-3.13}` default and the 3.15-as-opt-in policy.
- [x] 3.4 Add an interactive Python prompt (using `prompt_yes_no`, Task 2.4) "Use Python 3.15 (faster, prerelease)?" that sets `VER=3.15` on yes / keeps `3.13` on no; `YAS_PYTHON=3.15` (any mode) forces 3.15 and short-circuits the prompt. Thread the chosen `VER` into `provision_python`.

## 4. Side-effect-free preview rendering (`ops/install.sh`)

- [x] 4.1 Add a `render_preview(glyph_mode, theme)` helper that invokes `"$PYTHON_BIN" "$PLUGIN_ROOT/claude/statusline_command.py"` with stdin = `$PLUGIN_ROOT/ops/session-info-example.json`, env `YAS_GLYPH_MODE` / `YAS_THEME` set to the highlighted values, and a fixed `COLUMNS` (e.g. 100). Both shipped paths are git-tracked, so they exist under `$PLUGIN_ROOT`.
- [x] 4.2 Isolate side effects: point `CLAUDE_CONFIG_DIR` (hence `CLAUDE_DIR`, the base `app.main` uses for `statusline-output/`, see `claude/yas/app.py` ~lines 88–95) at a throwaway `mktemp -d` for the preview subprocess only, so the payload write lands in scratch and is discarded. Do NOT export the throwaway dir into the surrounding installer environment.
- [x] 4.3 Wire `render_preview` as the preview callback for the glyph-mode (Task 5.1) and theme (Task 5.2) selectors so highlight changes redraw the sample beneath the menu.

## 5. Config wizard (`ops/install.sh`, interactive only)

- [x] 5.1 **Glyph mode** prompt: single-select over the 4 values validated by `_parse_glyph_mode` (`claude/yas/config.py`): `nerdfont` (default), `ascii`, `unicode`, `github`, with the live preview callback. Capture the chosen value.
- [x] 5.2 **Theme** prompt: single-select over the 14 keys in `THEMES` (`claude/yas/themes.py`): `claude-dark` (default), `claude-light`, `catppuccin-latte`, `catppuccin-mocha`, `dracula`, `gruvbox-dark`, `gruvbox-light`, `nord`, `one-dark`, `one-light`, `solarized-dark`, `solarized-light`, `tokyo-night`, `palenight`, with the live preview callback.
- [x] 5.3 **Labels** prompt: `prompt_yes_no` defaulting to **on**; maps to `layout.labels`.
- [x] 5.4 **Soft limit** prompt: single-select preset menu `150000 / 200000 / 500000 / 1000000` (no free-form entry); after selection print a one-line pointer to the README / `yas.example.toml` for per-model `[[tokens.model]]` and advanced config. Maps to `tokens.soft_limit`.
- [x] 5.5 Order the wizard per design: in full mode the logo + Python prompt fire BEFORE `ensure_marketplace`/`ensure_plugin`; the four config prompts fire AFTER `provision_python` sets `PYTHON_BIN` (previews need the interpreter + shipped assets).

## 6. yas.toml generation: build, keep, write/print (`ops/install.sh`)

- [x] 6.1 Add `build_yas_toml(glyph_mode, labels, theme, soft_limit)` that emits a commented template mirroring `yas.example.toml`'s structure (sections `[layout]` `labels`, `[tokens]` `soft_limit`, `[appearance]` `theme`, `[appearance.glyphs]` `mode`) with the four chosen values interpolated. Do NOT merge an existing file's comments/keys.
- [x] 6.2 **Existing-file check**: before the questions, if `$CLAUDE_CONFIG_DIR/yas.toml` exists, prompt keep-as-is vs reconfigure. Keep skips the questions and any write.
- [x] 6.3 **After the questions**: prompt overwrite-file vs print-to-STDOUT. Overwrite writes atomically (`mktemp` + `mv`, matching the `do_wire` settings pattern at lines 461–464). Print emits `build_yas_toml` output to stdout only.
- [x] 6.4 Validate an overwrite by re-parsing with the provisioned Python's `tomllib` where available (`"$PYTHON_BIN" -c 'import tomllib,sys; tomllib.load(open(sys.argv[1],"rb"))' "$TOML"`); on failure, do not leave a corrupt file in place.
- [x] 6.5 Ensure non-interactive mode writes NO `yas.toml` (guard the whole wizard + write behind `INTERACTIVE`).

## 7. Reconfigure mode and main() dispatch (`ops/install.sh`)

- [x] 7.1 In `main()` (lines 582–595) add a `reconfigure` branch: require interactivity (error out if not interactive, since it has no non-interactive behaviour), then `print_logo` → Python prompt → discover `$PLUGIN_ROOT` (reuse `CLAUDE_PLUGIN_ROOT` or the `do_wire` discovery) → run wizard (Tasks 5–6) → re-run `do_wire`. SKIP `ensure_marketplace` / `ensure_plugin`.
- [x] 7.2 In the `full` branch of `main()`, thread the interactive flow per Task 5.5 (logo + Python prompt before marketplace; wizard + yas.toml after provisioning, before/around `do_wire`).
- [x] 7.3 Add a post-install message at the end of the wire/wizard flow pointing users to `/yas:config`, explicitly noting it as the way to switch to Python 3.15 later.

## 8. `/yas:config` skill

- [x] 8.1 Create `skills/config/SKILL.md` mirroring `skills/init/SKILL.md`'s frontmatter (`name: config`, `allowed-tools: Bash`, `effort: low`, `model: haiku`) and a description naming reconfiguration of glyph mode / theme / labels / soft-limit / Python version.
- [x] 8.2 Its `<workflow>` runs `bash "${CLAUDE_PLUGIN_ROOT}/ops/install.sh" --reconfigure`. Confirm `.claude-plugin/plugin.json` `source: "./"` packs `skills/config/` automatically (no allowlist to update).

## 9. Docs

- [x] 9.1 Update `README.md`: document interactive-default behaviour, the `YAS_NO_TTY=1` escape hatch, the `YAS_PYTHON` override and the new stable-3.13 default (note the 3.15 opt-in and ~6–8 ms tradeoff), and the `/yas:config` reconfigure skill.
- [x] 9.2 Update `yas.example.toml` only if a new commented knob is surfaced by the wizard; otherwise leave it (the four wizard knobs already appear there). No new knob surfaced — left unchanged.

## 10. Tests (`test/test_install_script.py` + docker harness)

- [x] 10.1 Add a test asserting the non-interactive default provisions/dry-run-previews **3.13** (assert the dry-run output names 3.13, mirroring the existing `test_wire_only_dry_run_previews_uv_bootstrap_when_uv_absent` pattern using `--dry-run`). Tests invoke `subprocess.run(['bash', INSTALL_SH, *args])` with no piped stdin (already non-TTY).
- [x] 10.2 Add a test that `YAS_NO_TTY=1` forces non-interactive: no prompt, no `yas.toml` written, selected mode completes (use `--dry-run` + env).
- [x] 10.3 Add a test that `YAS_PYTHON=3.15` overrides the version in the dry-run preview (output names 3.15).
- [x] 10.4 Add a `--reconfigure` test: with `CLAUDE_PLUGIN_ROOT` set and `YAS_NO_TTY=1`, assert it errors/exits cleanly without marketplace/plugin calls (non-interactive reconfigure has no behaviour) — i.e. assert no plugin management is attempted.
- [x] 10.5 Add an isolated yas.toml-builder test: invoke the `build_yas_toml` logic (e.g. via a small `bash -c` shim sourcing the function, or by exercising the print-to-STDOUT path) and assert the four chosen values appear under the right tables, then parse the output with `tomllib` to confirm validity. Note in a comment that the live interactive TTY path is not CI-testable (no tty).
- [x] 10.6 Extend `ops/install-docker-test/container-test.sh` to cover the end-to-end non-interactive provision/wire with the new 3.13 default (adjust the existing `assert_wired_3_15` S1/S2 assertions to the resolved version, or add a 3.13 assertion path).

## 11. Validation

- [x] 11.1 Run the install-script tests via the verifier (`uv run pytest -q test/test_install_script.py`) and `uv run ruff check`; full suite green once before merge.
- [x] 11.2 Run `openspec validate interactive-installer --strict` and confirm the change is apply-ready.
