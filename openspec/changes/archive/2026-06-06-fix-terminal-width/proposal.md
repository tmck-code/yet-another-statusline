## Why

The `terminal_width()` function probes width sources in the wrong order, and the tmux probe has no timeout. Claude Code (v2.1.153+) sets the `COLUMNS` environment variable to the exact pixel-accurate width it has allocated for the statusline; checking `COLUMNS` first makes the width instantaneous and correct. Meanwhile, the current tmux probe (checked first) can hang indefinitely when a tmux server is wedged, blocking every statusline render until Claude Code kills the process.

## What Changes

- `terminal_width()` in `render/text.py` will check `COLUMNS` as its **first** source, before any subprocess or file read.
- The `subprocess.run` tmux probe will gain `timeout=0.2` so a wedged tmux server blocks the render for at most 200 ms rather than indefinitely.
- Source order after the fix: `COLUMNS` → tmux (with timeout) → `CLAUDE_DIR/terminal-width` file → `shutil.get_terminal_size` → `os.get_terminal_size` fds → `/dev/tty`.

## Capabilities

### New Capabilities

- `terminal-width-resolution`: Width is resolved by checking `COLUMNS` first (instant, authoritative when Claude Code sets it), with a bounded tmux fallback.

### Modified Capabilities

*(none — same function, corrected probe order and timeout)*

## Impact

- `claude/yas/render/text.py`: `terminal_width()` function
- Tests: any test that stubs `COLUMNS` or mocks the tmux probe may need updating
