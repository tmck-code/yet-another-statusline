# YAS! (Yet Another Statusline)

<img width="1685" height="320" alt="image" src="https://github.com/user-attachments/assets/516cb692-3318-4552-b813-e3e34ca96858" />

_Most common form is displaying these stats, which include the loaded plugins & skills. Extra sections appear as needed_

To install (note: currently requires a ["Nerd font"](https://www.nerdfonts.com/font-downloads) for the icons):

```bash
make install
```

This symlinks the files into your `~/.claude/` user dir, allowing you to easily update them via a `git pull`

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

To demo/test:

```bash
make demo
```

## Contributing

Enable the git pre-commit hooks (runs `ruff` / `mypy` / `pytest` on staged Python before each commit):

```bash
make hooks
```

This prompts before setting `core.hooksPath`. CI runs the same checks on every push, so the hook is fast local feedback rather than the gate.
