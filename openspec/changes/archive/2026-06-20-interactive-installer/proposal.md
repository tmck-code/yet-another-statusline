## Why

`ops/install.sh` today has zero interactivity: full mode silently registers the
marketplace, installs the plugin, provisions a **3.15 alpha** interpreter, and
wires `settings.json` with no prompt and no opportunity to pick a theme, glyph
mode, labels, or a token soft-limit. A first-time user under `curl … | bash`
gets an opinionated, prerelease-Python install they never consented to, and the
only way to discover the four user-facing config knobs is to read the source or
`yas.example.toml`. There is also no in-app reconfigure path — no `/yas:config`
skill exists. We can offer a guided first-run experience without breaking the
non-interactive CI / plugin-wiring path the script already serves.

## What Changes

- **Interactive-by-default install.** When `install.sh` runs attached to a
  terminal it shows the YAS logo, prompts for the Python version, runs a config
  wizard (glyph mode, labels, theme, soft-limit) with **live render previews**,
  and writes `$CLAUDE_CONFIG_DIR/yas.toml`. Interactivity is suppressed when
  `YAS_NO_TTY=1` **or** no readable `/dev/tty` exists (CI safety — the installer
  must never block on input). Under `curl | bash` the script reopens stdin once
  via `exec < /dev/tty` (no re-download, no re-exec).
- **Self-contained, no untracked-asset dependency.** The plain logo and a
  minimal **single-select function derived from blurayne's `select.sh`** (CC
  BY 4.0) are embedded directly in `install.sh` as a heredoc / bash function.
  `select.sh` / `checkbox.sh` / `yas.dos_rebel*.txt` stay dev-only — they are
  git-untracked and so are never shipped in `$PLUGIN_ROOT`. The embedded
  selector is **bash-3.2-safe** (no associative arrays, no `${var,,}`) so stock
  macOS bash works, reads `/dev/tty`, and supports a render-on-highlight preview
  callback.
- **Python version policy change. BREAKING (default behaviour).** Provision
  `VER=${YAS_PYTHON:-3.13}` instead of the current hardcoded 3.15. The
  non-interactive / plugin (wire-only) path now defaults to the **stable 3.13**
  rather than silently shipping a Python **alpha**. Interactive mode prompts
  "Use Python 3.15 (faster, prerelease)?". `YAS_PYTHON=3.15` forces 3.15 in any
  mode. This trades the ~6–8 ms startup win on silent installs for not
  installing a prerelease without consent; it is fully recoverable later via
  `/yas:config`.
- **Config wizard writes `yas.toml` (interactive only).** Four prompts map to
  `appearance.glyphs.mode`, `layout.labels`, `appearance.theme`,
  `tokens.soft_limit`, rendered from a commented template. Glyph mode and theme
  use render-on-highlight live samples; labels defaults to **on** for new users;
  soft-limit is a **preset menu** (150k / 200k / 500k / 1M) with a pointer to the
  README for advanced/per-model config. Non-interactive mode writes **no**
  `yas.toml`. An existing `yas.toml` triggers a keep-as-is vs reconfigure prompt,
  and after the questions an overwrite-file vs print-to-STDOUT choice.
- **`--reconfigure` mode + `/yas:config` skill.** A new `--reconfigure` mode
  re-runs the logo + full wizard (Python + 4 options + write `yas.toml` +
  re-wire) and **skips** marketplace/plugin install. A new plugin skill
  `skills/config/SKILL.md` exposes it as `/yas:config`, which the post-install
  message points users to (including as the way to switch to 3.15 later).
- **Docs + tests.** README documents interactive-default behaviour, `YAS_NO_TTY`,
  `YAS_PYTHON`, and `/yas:config`. Tests cover the non-interactive 3.13 default,
  `YAS_NO_TTY=1` forcing non-interactive, the `YAS_PYTHON=3.15` override,
  `--reconfigure`, and the yas.toml template builder in isolation. The live TTY
  path is not CI-testable; the docker harness covers end-to-end provision/wire.

## Capabilities

### New Capabilities
<!-- None — this change modifies the existing install-script capability. -->

### Modified Capabilities
- `install-script`: adds an interactive mode (TTY-detected, default-on, with
  `YAS_NO_TTY` / `/dev/tty` escape hatches), an embedded logo + bash-3.2-safe
  single-select with render-on-highlight previews, a `YAS_PYTHON`-driven version
  policy whose non-interactive default changes from 3.15 to 3.13, an interactive
  config wizard that writes `yas.toml` (with keep/reconfigure and
  overwrite/print choices), a `--reconfigure` mode, and a `/yas:config` skill
  delegating to it.

## Impact

- **Modified**: `ops/install.sh` (TTY detection + `YAS_NO_TTY`; `exec < /dev/tty`;
  embedded logo heredoc; embedded `select.sh`-derived single-select; `VER`-driven
  `provision_python` replacing the hardcoded 3.15; interactive Python prompt;
  config wizard with live previews; `yas.toml` template builder + write/keep/print;
  `--reconfigure` mode + arg parsing; post-install `/yas:config` pointer).
- **New**: `skills/config/SKILL.md` → `/yas:config` runs
  `bash "$CLAUDE_PLUGIN_ROOT/ops/install.sh" --reconfigure`.
- **Modified**: `openspec/specs/install-script/spec.md` (interactive mode, TTY
  detection, embedded assets, Python version policy, config wizard, reconfigure,
  skill).
- **Modified**: `test/test_install_script.py` (non-interactive 3.13 default;
  `YAS_NO_TTY=1`; `YAS_PYTHON=3.15`; `--reconfigure`; yas.toml builder in
  isolation). **Modified**: `ops/install-docker-test/` end-to-end provision/wire.
- **Modified**: `README.md` (interactive-default, `YAS_NO_TTY`, `YAS_PYTHON`,
  `/yas:config`); `yas.example.toml` if a new commented knob is surfaced.
- **No change** to the renderer (`claude/yas/**`) or runtime statusline behaviour.
  The wizard *invokes* `statusline_command.py` read-only for previews.
- **Dependencies**: unchanged tool contract (`claude` + `curl` + system Python
  ≥3.10 for full; system Python ≥3.10 for wire-only; `uv` auto-bootstrapped).
  `/dev/tty` is used only when present.
