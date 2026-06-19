## Context

`ops/install.sh` is a single bash script (`#!/usr/bin/env bash`, `set -uo
pipefail`, POSIX-ish, no bash-4 features) with two auto-detected modes keyed on
`CLAUDE_PLUGIN_ROOT`: **full** (`ensure_marketplace` → `ensure_plugin` →
`do_wire`) and **wire-only** (`do_wire` only), plus `--uninstall`, `--dry-run`,
`--main`. It has **zero TTY/interactivity**. All JSON goes through the
injection-safe `json_py()` bash→Python heredoc (jq was dropped). `do_wire`
discovers `$PLUGIN_ROOT`, calls `provision_python "$PLUGIN_ROOT"` (which
bootstraps `uv` into `$PLUGIN_ROOT/.uv` with `INSTALLER_NO_MODIFY_PATH=1` and
installs CPython **3.15** into `$PLUGIN_ROOT/.python`, hardcoded), falls back to
`find_python` (system ≥3.10, avoids 3.14), then atomically writes
`statusLine.command` into `$CLAUDE_CONFIG_DIR/settings.json` (backup → temp → mv
→ `json_py validate` → restore-on-failure).

The README install command pipes the script into bash:
`curl -fsSL …/main/ops/install.sh | bash`. Under a pipe, the shell's stdin is
the pipe, not a terminal — so any naive `read` would consume the script body or
hit EOF.

Config lives in `claude/yas/config.py` (`Config.load`, precedence CLI → `YAS_*`
env → legacy-alias env → `yas.toml` → default). The four user-facing knobs:
`appearance.glyphs.mode` / `YAS_GLYPH_MODE` (`nerdfont` default / `ascii` /
`unicode` / `github`, validated by `_parse_glyph_mode`); `layout.labels` /
`YAS_LABELS` (bool, default `False`); `appearance.theme` / `YAS_THEME` (the 14
keys in `THEMES` in `claude/yas/themes.py`, `claude-dark` default, validated by
`_parse_theme`); `tokens.soft_limit` / `YAS_SOFT_LIMIT` (int > 0, default
150000; per-model overrides via `[[tokens.model]]`). `yas.toml` lives at
`$CLAUDE_CONFIG_DIR/yas.toml`; `yas.example.toml` is the committed template;
`tomllib` is read-only (3.11+) — there is **no stdlib TOML writer**.

**Untracked-asset finding (load-bearing):** the logo `yas.dos_rebel.plain.txt`,
plus `select.sh`, `checkbox.sh`, and `yas.dos_rebel.txt`, are **git-untracked**
(verified via `git ls-files`). Claude Code plugin packaging ships only
git-tracked files, so none of these reach `$PLUGIN_ROOT` after install, and none
exist under `curl | bash`. `ops/session-info-example.json` and
`claude/statusline_command.py` **are** tracked and shipped.

## Goals / Non-Goals

**Goals:**
- A guided, default-on first-run experience (logo → Python prompt → 4 config
  prompts with live previews → write `yas.toml`) when attached to a terminal.
- Never block on input in CI / non-TTY / `YAS_NO_TTY=1` contexts; the
  non-interactive path stays behaviourally identical **except** the Python
  default moves 3.15 → 3.13.
- Self-containment: zero runtime dependency on untracked assets; logo + selector
  embedded in the script.
- Stop silently shipping a prerelease Python; make 3.15 an explicit opt-in.
- An in-app reconfigure entry point (`/yas:config` → `--reconfigure`).

**Non-Goals:**
- Editing the renderer (`claude/yas/**`) or any statusline runtime behaviour.
- A TOML round-trip merge that preserves a user's existing comments/keys — the
  keep-as-is vs reconfigure and overwrite vs print choices cover that instead.
- Free-form numeric soft-limit entry or per-model `[[tokens.model]]` editing in
  the wizard — preset menu only, with a README pointer for advanced config.
- Multi-select prompts (`checkbox.sh`) — all four prompts are single-select /
  yes-no.
- CI-testing the live interactive TTY render path (no terminal in CI).
- Re-downloading or re-`exec`ing the script to obtain a TTY.

## Decisions

### 1. Interactivity / TTY model
- **Interactive is the default.** Force non-interactive when `YAS_NO_TTY=1`
  **OR** no readable `/dev/tty`. A single predicate (e.g. `is_interactive()`,
  `INTERACTIVE=1` when `[ -z "${YAS_NO_TTY:-}" ] && [ "$YAS_NO_TTY" != "1" ]`
  and `[ -r /dev/tty ]`) gates every prompt. No prompt is ever issued when the
  predicate is false — the script must never hang.
- **Reopen stdin once via `exec < /dev/tty`** at the start of the interactive
  branch. This works under `curl | bash` because bash has already read the
  entire script body from the pipe before `main` runs, so the pipe is exhausted
  and reattaching fd 0 to the terminal is safe. No re-download, no re-exec, no
  subshell. The embedded selector additionally reads `/dev/tty` directly for
  keystrokes so it is robust regardless of fd-0 state.
- `--reconfigure` implies interactive intent; if its preconditions for a TTY are
  not met it errors out rather than silently doing nothing (it has no useful
  non-interactive behaviour).

### 2. Self-contained embedded assets
- **Logo**: embed `yas.dos_rebel.plain.txt`'s 8 lines (42 cols, plain unicode
  block art) as a single-quoted heredoc printed by a `print_logo()` function.
  Source of truth is the heredoc, **not** a file read — chosen over git-tracking
  the logo so the script is self-contained under `curl | bash` and inside
  `$PLUGIN_ROOT`. The untracked logo file stays as the dev-time authoring source.
- **Selector**: embed a minimal single-select bash function derived from
  blurayne's `select.sh` (the vendored gist). It MUST: read `/dev/tty` for input
  (arrow keys + enter), return the chosen index/value via a global (matching the
  upstream `UI_WIDGET_RC` convention), be **bash-3.2-safe** (no associative
  arrays, no `${var,,}`, no `mapfile`), and accept an **optional preview
  callback** invoked on each highlight change with the highlighted value so the
  caller can render a live sample. Preserve a **CC BY 4.0 attribution comment**
  for blurayne above the embedded function.
- `select.sh` / `checkbox.sh` remain dev-only and are NOT a runtime dependency.

### 3. Python version policy (`provision_python` reads `VER`)
- `provision_python` currently hardcodes `3.15` in five places (the dry-run
  messages at lines ~239 / ~241, the `uv python install 3.15`, the
  `uv python find 3.15`, and the `find … -name python3.15 -path '*/cpython-3.15*'`
  fallback glob). Parameterise on a `VER` resolved as `${YAS_PYTHON:-3.13}`,
  overridden to the interactive choice when the user is prompted. Every literal
  `3.15` token in the function becomes `$VER` (including the glob's
  `python$VER` / `cpython-$VER*`).
- **Default by mode**: non-interactive / wire-only → `3.13`. Interactive → prompt
  "Use Python 3.15 (faster, prerelease)?" → yes sets `VER=3.15`, no keeps `3.13`.
  `YAS_PYTHON=3.15` (any mode) forces `3.15` and suppresses the prompt's effect.
- The `find_python` system fallback already prefers non-3.14 and includes
  `python3.13`/`python3.15` candidates, so it needs no change for the new default.

### 4. Config wizard flow (interactive only)
Full-mode order — the Python prompt and logo fire **before** plugin install
(they need no shipped asset, being embedded); the live previews fire **after**
`provision_python` (they need the interpreter plus the shipped
`$PLUGIN_ROOT/claude/statusline_command.py` and
`$PLUGIN_ROOT/ops/session-info-example.json`):

1. `print_logo`
2. Python-version prompt (Decision 3)
3. `preflight_full`
4. `ensure_marketplace`
5. `ensure_plugin` (lands renderer + sample JSON at `$PLUGIN_ROOT`)
6. `provision_python` → `PYTHON_BIN`
7. Config questions with live previews (below)
8. Write `yas.toml` (Decision 5)
9. `do_wire` settings.json write
10. Post-install message → `/yas:config`

The four prompts:
- **glyph mode** (4 options) and **theme** (14 options): **render-on-highlight**
  preview. The preview callback runs the provisioned `PYTHON_BIN` on
  `$PLUGIN_ROOT/claude/statusline_command.py` with stdin =
  `$PLUGIN_ROOT/ops/session-info-example.json` and `YAS_GLYPH_MODE` /
  `YAS_THEME` set to the highlighted value, plus a fixed `COLUMNS` (e.g. 100) so
  the sample box geometry is stable, and prints the rendered statusline beneath
  the menu.
- **labels**: yes/no, prompt **defaults to on** for new users (rationale: aids
  familiarity with the labelled rows). Maps to `layout.labels`.
- **soft limit**: **preset menu only** — 150k / 200k / 500k / 1M — followed by a
  one-line pointer to the README / `yas.example.toml` for per-model and advanced
  config. **No** free-form numeric entry. Maps to `tokens.soft_limit`.

### 5. yas.toml write, keep, and print (interactive only)
- The wizard generates `yas.toml` from a **commented template** baked into the
  script (a `build_yas_toml()` function that interpolates the four chosen values
  into a heredoc mirroring `yas.example.toml`'s structure:
  `[layout] labels`, `[tokens] soft_limit`, `[appearance] theme`,
  `[appearance.glyphs] mode`). No merge of an existing file's comments/keys is
  attempted.
- **Existing `yas.toml` detected** → prompt **keep as-is** vs **reconfigure**.
  Keep skips the four questions and the write entirely.
- **After the questions** → prompt **overwrite the file** vs **print to STDOUT**
  (for manual copy/paste). The overwrite path writes atomically (temp + mv) and
  validates by re-parsing with the provisioned Python's `tomllib` where available
  (3.11+); print just emits to stdout.
- **Non-interactive mode writes NO `yas.toml`** — env vars and defaults govern.

### 6. `--reconfigure` mode + `/yas:config` skill
- New `--reconfigure` flag in the arg loop sets `MODE="reconfigure"`. The
  `reconfigure` branch in `main()`: `print_logo` → Python prompt → run the full
  interactive wizard (4 options + write `yas.toml`) → re-run `do_wire`. It
  **skips** `ensure_marketplace` / `ensure_plugin` (plugin already present) and
  reuses `$PLUGIN_ROOT` via `CLAUDE_PLUGIN_ROOT` / the same `do_wire` discovery.
- New `skills/config/SKILL.md` (mirroring `skills/init/SKILL.md`'s frontmatter:
  `allowed-tools: Bash`, `effort: low`, `model: haiku`) whose workflow is
  `bash "${CLAUDE_PLUGIN_ROOT}/ops/install.sh" --reconfigure`. Resolves as
  `/yas:config`.
- The post-install message (end of `do_wire` / the wizard) points users to
  `/yas:config`, explicitly noting it as the way to switch to Python 3.15 later.

### 7. Side-effect-free previews
`app.main()` (`claude/yas/app.py`, lines ~88–95) writes
`$CLAUDE_DIR/statusline-output/statusline.<session_id>.json` keyed on the stdin
payload's `session_id`, and (when `show_render_time` is on) touches a
`RenderTiming` cache. Previews must not pollute a real session's output. The
preview invocation SHALL neutralise this by pointing `CLAUDE_CONFIG_DIR` (hence
`CLAUDE_DIR`, the base for `statusline-output`) at a throwaday temp dir for the
duration of the preview subprocess, so any payload write lands in scratch space
and is discarded. (`session-info-example.json`'s `session_id` is itself a sample
id; isolating `CLAUDE_DIR` is the robust guarantee.) The write is already wrapped
in `try/except OSError`, so a read-only scratch dir would also be safe, but an
isolated writable temp dir keeps the render path identical to production.

## Risks / Trade-offs

- **3.13 default is a behaviour change (BREAKING for the silent default).**
  Silent installs lose the ~6–8 ms 3.15 startup win. Accepted: shipping a Python
  **alpha** without consent is worse, and it is recoverable via `YAS_PYTHON=3.15`
  or `/yas:config`. Documented in README + the post-install message.
- **Preview side effects** — mitigated by Decision 7 (isolated `CLAUDE_CONFIG_DIR`
  per preview). The exact env knob and the throwaway-dir lifecycle are specified
  in tasks; verify against `app.main()`'s `CLAUDE_DIR / 'statusline-output'`
  path construction before wiring previews.
- **Embedded selector portability** — must be bash-3.2-safe and read `/dev/tty`.
  Risk that `exec < /dev/tty` interacts badly with `do_wire`'s later `json_py` /
  `uv` subprocesses; mitigated because those subprocesses get their stdin from
  heredocs / files (`json_py` uses `<<'PY'`; `uv`/`curl` read no stdin), not from
  fd 0, so reattaching fd 0 to the terminal is inert for them. Validate in the
  docker harness.
- **CC BY 4.0 attribution** must be preserved verbatim in the embedded selector;
  the upstream `checkbox.sh` (Pedro) is not embedded.
- **Logo as embedded heredoc vs git-tracked file** — recommended: embedded
  heredoc as the single source of truth (self-contained). Git-tracking the logo
  would be an alternative but still requires the heredoc for `curl | bash`, so it
  buys nothing; the untracked file remains the dev authoring source.
- **No CI coverage of the live TTY path** — accepted. Tests target the
  non-interactive branches and the pure builders (`build_yas_toml`, the selector
  logic in isolation); the docker harness covers end-to-end provision/wire.
