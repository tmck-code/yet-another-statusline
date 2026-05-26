# YAS! (Yet Another Statusline)

<img width="1685" height="320" alt="image" src="https://github.com/user-attachments/assets/516cb692-3318-4552-b813-e3e34ca96858" />

_Most common form is displaying these stats, which include the loaded plugins & skills. Extra sections appear as needed_

## Requirements

- Python 3.10+
- [Nerd Font](https://www.nerdfonts.com/font-downloads) (for icons)

## Install

### Via Claude Code plugin (recommended)

```bash
claude plugin marketplace add tmck-code/yet-another-statusline
claude plugin install yas@yet-another-statusline
claude -p "/yas:init"
```

`/yas:init` wires `statusLine.command` into `~/.claude/settings.json`. Reload Claude Code after it completes.

**Upgrade:**
```bash
claude plugin install yas@yet-another-statusline
claude -p "/yas:init"
```

`/yas:init` detects the new versioned path and rewrites it automatically.

**Uninstall:**
```bash
claude -p "/yas:uninstall"
claude plugin uninstall yas@yet-another-statusline
```

`claude plugin uninstall` only deletes the plugin cache — it leaves `statusLine.command`
in `~/.claude/settings.json` pointing at the now-missing script, so the statusline keeps
trying to run. Run `/yas:uninstall` **first** to remove that config (it backs up
settings.json, and skips a custom non-yas statusLine) and clear the renderer's runtime
logs. Reload Claude Code afterwards.

### Via git clone (contributors / live-edit)

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

## Demo

A dummy session to demonstrate the layout:

<img width="1524" height="530" alt="statusline-demo-1779720526" src="https://github.com/user-attachments/assets/6be6e870-5207-4737-89f4-b85723c86620" />

## Layout Reference

<img width="1835" height="884" alt="image" src="https://github.com/user-attachments/assets/4a410cd6-5afa-401d-b3f0-5b8726187a03" />

## Widths

The statusline also renders differently according to available width

| mode | width | screenshot |
|------|-------|------------|
| "medium" | <=80 pixels | <img width="839" height="122" alt="image" src="https://github.com/user-attachments/assets/56519acc-a65c-446a-a938-5a14f093c817" /> |
| "narrow" | <=55 pixels | <img width="537" height="120" alt="image" src="https://github.com/user-attachments/assets/7254cbb7-ea37-4f41-8adc-506cf6b48033" /> |

---

## Configuration

The statusline is configured through CLI arguments and environment variables, plus a couple of optional files under your Claude config dir (`~/.claude` by default).

### CLI arguments

Pass these in the `statusLine.command` of your `~/.claude/settings.json`:

| arg | values | default | description |
|-----|--------|---------|-------------|
| `--theme NAME` | `claude-dark`, `claude-light`, `catppuccin-latte`, `catppuccin-mocha` | `claude-dark` | colour theme |
| `--bg-shift DIR` | `warm`, `cool` | `warm` | direction of the background gradient shift |

Both also accept the `--theme=NAME` / `--bg-shift=DIR` form.

### Environment variables

| var | default | description |
|-----|---------|-------------|
| `CLAUDE_CONFIG_DIR` | `~/.claude` | base dir for config/state files (theme file, width file, token-rate log, output payloads) |
| `CLAUDE_STATUSLINE_THEME` | _(unset)_ | theme name; overrides the config file, overridden by `--theme` |
| `STATUSLINE_TOKEN_WINDOW` | `60` | seconds; rolling window used to compute the token throughput rate |
| `COLUMNS` | _(unset)_ | terminal-width fallback when tmux / width-file detection fail |

### Theme resolution

The theme is chosen by the first of these that names a known theme:

1. `--theme NAME` CLI arg
2. `CLAUDE_STATUSLINE_THEME` env var
3. `~/.claude/statusline-theme` file (contents = theme name)
4. built-in default (`claude-dark`)

### Terminal width

Width is detected by the first source that returns a positive value:

1. `tmux display-message -p '#{pane_width}'`
2. `~/.claude/terminal-width` file
3. `COLUMNS` env var
4. `shutil.get_terminal_size()` / `/dev/tty` ioctl

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

This prompts before setting `core.hooksPath`. CI runs the same checks on every push, so the hook is fast local feedback rather than the gate.
