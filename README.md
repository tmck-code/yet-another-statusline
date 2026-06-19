# YAS! (Yet Another Statusline)

🌈 Check out the official landing page here: [YAS! Yet Another Statusline](https://tmck-code.github.io/pages/yas.html)

<img width="1685" height="320" alt="image" src="https://github.com/user-attachments/assets/516cb692-3318-4552-b813-e3e34ca96858" />

_Most common form is displaying these stats, which include the loaded plugins & skills. Extra sections appear as needed_

## Install/Update

Requires Python 3.10+, and a [Nerd Font](https://www.nerdfonts.com/font-downloads) to render the icons.

```bash
curl -fsSL https://raw.githubusercontent.com/tmck-code/yet-another-statusline/main/ops/install.sh | bash
```

Or install manually:

```bash
claude plugin marketplace add tmck-code/yet-another-statusline
claude plugin install yas@yet-another-statusline
claude -p "/yas:init"
```

### Interactive install

When run attached to a terminal the installer is **interactive by default**: it
shows the logo, asks whether to use Python 3.15, then runs a short wizard (glyph
mode, theme, labels, token soft-limit) with **live render previews** and writes a
`yas.toml` for you. Under `curl … | bash` it reopens the terminal once via
`/dev/tty` to drive the prompts (no re-download, no re-exec).

- **`YAS_NO_TTY=1`** — force the fully non-interactive flow (no prompts, no
  `yas.toml` written). This is also the automatic behaviour in CI or any context
  with no readable `/dev/tty`, so the installer never blocks on input.
- **`YAS_PYTHON`** — pick the private CPython version the installer provisions.
  The default is now the **stable 3.13** (the non-interactive default no longer
  silently installs a prerelease). Set `YAS_PYTHON=3.15` (any mode) to opt into
  3.15, which starts ~6–8 ms faster but is currently a prerelease.

### Reconfigure later — `/yas:config`

Run `/yas:config` any time to re-run the wizard against the already-installed
plugin — switch theme/glyph mode, toggle labels, change the soft limit, or move
to Python **3.15**. It re-wires `settings.json` without re-registering the
marketplace or reinstalling the plugin.

## Demo

A dummy session to demonstrate the layout:

<img width="3084" height="1250" alt="yas-0 2 5" src="https://github.com/user-attachments/assets/94d318c7-d7b4-4ad0-a06c-90f303d7f9a7" />

## Layout Reference

<img width="1834" height="979" alt="image" src="https://github.com/user-attachments/assets/9c3137b4-dd01-478e-b3bb-6b9d39570104" />

## Widths

The statusline also renders differently according to available width

| mode | width | screenshot |
|------|-------|------------|
| "medium" | <=80 pixels | <img width="839" height="122" alt="image" src="https://github.com/user-attachments/assets/56519acc-a65c-446a-a938-5a14f093c817" /> |
| "narrow" | <=55 pixels | <img width="537" height="120" alt="image" src="https://github.com/user-attachments/assets/7254cbb7-ea37-4f41-8adc-506cf6b48033" /> |

---

## Configuration

Every configurable knob resolves through one fixed precedence chain (highest wins):

```
CLI flag  →  canonical YAS_* env var  →  legacy-alias env var  →  yas.toml  →  built-in default
```

The first source in that chain that is **present and valid** wins; an absent or
invalid source falls through to the next (an empty-string env var counts as
absent). Canonical `YAS_*` env vars always win over their deprecated legacy
aliases when both are set — the aliases keep working but are deprecated.

### Knobs

| Knob | Env var | Legacy alias | `yas.toml` key | Default |
|------|---------|--------------|----------------|---------|
| `max_width` | `YAS_MAX_WIDTH` | — | `[layout].max_width` | `140` |
| `full_width` | `YAS_FULL_WIDTH` | — | `[layout].full_width` | `false` |
| `soft_limit` | `YAS_SOFT_LIMIT` | — | `[tokens].soft_limit` | `150000` |
| `token_window` | `YAS_TOKEN_WINDOW` | `STATUSLINE_TOKEN_WINDOW` | `[tokens].token_window` | `60` |
| `theme` | `YAS_THEME` (also `--theme` CLI) | `CLAUDE_STATUSLINE_THEME` | `[appearance].theme` | `claude-dark` |
| `bg_shift` | `YAS_BG_SHIFT` (also `--bg-shift` CLI) | — | `[appearance].bg_shift` | `warm` |
| `glyph_mode` | `YAS_GLYPH_MODE` (also `--glyph-mode` CLI) | — | `[appearance.glyphs].mode` | `nerdfont` |
| `single_width` | `YAS_GLYPH_SINGLE_WIDTH` (also `--glyph-single-width` CLI) | — | `[appearance.glyphs].single_width` | `false` |
| `show_render_time` | `YAS_SHOW_RENDER_TIME` | — | `[layout].show_render_time` | `false` |

- Valid `theme` values (14 built-in themes):
  - **Dark:** `claude-dark`, `catppuccin-mocha`, `dracula`, `gruvbox-dark`, `nord`, `one-dark`, `solarized-dark`, `tokyo-night`, `palenight`
  - **Light:** `claude-light`, `catppuccin-latte`, `gruvbox-light`, `one-light`, `solarized-light`

  An unknown or unset `theme` falls back to `claude-dark`.
- Valid `bg_shift` values: `warm` or `cool`.
- Valid `glyph_mode` values: `nerdfont` (default; full fidelity, needs a Nerd Font), `ascii` (every non-ASCII glyph → width-1 ASCII; maximum compatibility), `unicode` (only Nerd Font PUA icons → non-PUA Unicode; keeps box/block/arrow glyphs), `github` (GitHub-paste-safe: folds every glyph a browser renders double-wide — the box-drawing frame, block/sparkline ramp, and EAW-ambiguous punctuation/icons — to a width-1, EAW-narrow/ASCII stand-in, so a render stays column-aligned when pasted into a GitHub markdown code block). All modes preserve column geometry. An unknown value falls back to `nerdfont`.
- `single_width` is an orthogonal boolean that folds double-width dynamic content (wide emoji, CJK in branch names/paths) to width-1; it may be combined with any `glyph_mode`. The statusline's own glyphs are already width-1, so column geometry is preserved.
- `full_width`, when `true`, makes the box fill the terminal and ignore `max_width`.
- `show_render_time`, when `true`, annotates the bottom-right border with the previous run's wall-clock render time (e.g. `…47.2ms──╯`). Off by default; each run shows the prior run's timing, so it is blank on a session's first render.
- The `--theme NAME` / `--bg-shift DIR` CLI flags also accept the `--theme=NAME` / `--bg-shift=DIR` form. Pass them in the `statusLine.command` of your `~/.claude/settings.json`.
- The legacy `~/.claude/statusline-theme` file (contents = a theme name) still works as the lowest-priority theme fallback, below `[appearance].theme`.

### `yas.toml`

`yas.toml` lives in `CLAUDE_CONFIG_DIR` (defaults to `~/.claude/`). It is **not**
auto-created — its absence simply means all-defaults — and `/yas:init` never
writes it. See [`yas.example.toml`](yas.example.toml) for a fully-commented
template; copy it to `~/.claude/yas.toml` and uncomment what you want.

```toml
[layout]
max_width = 140

[tokens]
soft_limit = 150000
token_window = 60

[appearance]
theme = "claude-dark"
bg_shift = "warm"

[appearance.glyphs]
mode = "nerdfont"
single_width = false
```

> **`yas.toml` requires Python 3.11+** — it is parsed with the stdlib `tomllib`.
> On Python 3.10 the file is silently skipped; **environment variables work on
> every Python version**.

Bad config never crashes the statusline. A malformed `yas.toml` is ignored
wholesale, and a single bad / out-of-range / wrong-type value drops only that
one knob back to its default. When any `yas.toml` value is rejected, a compact
warning row — `⚠ yas.toml: N values ignored (...)` — appears at the bottom of
the box listing the rejected knob names. Detailed per-value reasons go to stderr
only when `YAS_DEBUG` is set.

### Per-model `soft_limit` overrides

Beyond the global `[tokens].soft_limit`, you can declare per-model overrides as
an inline array under `[tokens]`:

```toml
[tokens]
model = [
    { match = "opus",         soft_limit = 200000 },   # the whole Opus family
    { match = "opus-4-8[1m]", soft_limit = 1000000 },  # 1M-context variant (longer match wins)
]
```

- `match` is a **case-insensitive plain substring** (no glob/regex), tested
  against the model's id and display name.
- When multiple entries match, the **longest** `match` wins; ties break by array
  order (first wins). If no entry matches, the global `soft_limit` is used. So to
  single out a variant from its family, give the variant the **longer, more
  specific** `match` (above, `opus-4-8[1m]` outranks `opus` for the 1M model).
- **A matching per-model override beats the global `soft_limit` from _any_
  source — including the `YAS_SOFT_LIMIT` environment variable.** This is the
  one documented exception to the "env beats `yas.toml`" rule: specificity beats
  source precedence (there is intentionally no per-model env var). It lets you
  raise the compaction-risk threshold for a 1M-context model variant distinctly
  from the rest of its family.

### Other environment variables

| var | default | description |
|-----|---------|-------------|
| `CLAUDE_CONFIG_DIR` | `~/.claude` | base dir for config/state files (`yas.toml`, theme file, width file, token-rate log, output payloads) |
| `YAS_DEBUG` | _(unset)_ | when set, prints detailed per-value config-rejection reasons to stderr |
| `COLUMNS` | _(unset)_ | terminal-width fallback when tmux / width-file detection fail |

### Terminal width

Width is detected by the first source that returns a positive value:

1. `tmux display-message -p '#{pane_width}'`
2. `~/.claude/terminal-width` file
3. `COLUMNS` env var
4. `shutil.get_terminal_size()` / `/dev/tty` ioctl

---

## Uninstalling

Remove the statusline config and uninstall the plugin in one step:

```bash
curl -fsSL https://raw.githubusercontent.com/tmck-code/yet-another-statusline/main/ops/install.sh | bash -s -- --uninstall --full
```

Or uninstall manually:

```bash
claude -p "/yas:uninstall"
claude plugin uninstall yas@yet-another-statusline
```

`claude plugin uninstall` only deletes the plugin cache — it leaves `statusLine.command`
in `~/.claude/settings.json` pointing at the now-missing script, so the statusline keeps
trying to run. Run the uninstall script (or `/yas:uninstall`) **first** to remove that
config, then uninstall the plugin. Reload Claude Code afterwards.

---

## Commands

```bash
make test            # run pytest suite
make demo            # animated demo at current terminal width
make statusline/test # same as demo — use during development
make demo/img        # render snapshots into demo/
make mon/run         # launch multi-session monitor TUI
```

## Contributing

Enable the git pre-commit hooks (runs `ruff` / `mypy` / `pytest` on staged Python before each commit):

```bash
make hooks
```

### Installing via git clone

Edits to the checkout take effect immediately — no reinstall step.

```bash
git clone https://github.com/tmck-code/yet-another-statusline
cd yet-another-statusline
```

Wire `statusLine.command` in `~/.claude/settings.json` to point at the checkout:
```json
"statusLine": {
  "async": true,
  "command": "python3 \"/path/to/yet-another-statusline/claude/statusline_command.py\"",
  "type": "command"
}
```

> **Note:** if you also have the plugin installed, `claude plugin install` will overwrite
> `statusLine.command` back to the plugin cache path. Either uninstall the plugin or bump
> the version in `.claude-plugin/plugin.json` before reinstalling to keep your local path.


This prompts before setting `core.hooksPath`. CI runs the same checks on every push, so the hook is fast local feedback rather than the gate.

