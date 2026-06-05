## Context

`terminal_width()` in `render/text.py` probes width in this order: tmux (subprocess) → `CLAUDE_DIR/terminal-width` file → `COLUMNS` env → `shutil.get_terminal_size` → fd probes → `/dev/tty`.

Claude Code v2.1.153+ sets `COLUMNS` to the exact width it allocated for the statusline before invoking the process. This is always the right answer when present, but it's currently checked third. Meanwhile, the tmux subprocess (checked first) has no timeout; a wedged tmux server blocks every render until the OS kills the subprocess.

## Goals / Non-Goals

**Goals:**
- Check `COLUMNS` first — it is instant, zero-subprocess, and authoritative when Claude Code sets it
- Add `timeout=0.2` to the `subprocess.run` tmux probe so a wedged server is bounded to 200 ms
- Preserve the rest of the fallback chain unchanged

**Non-Goals:**
- Removing any fallback source
- Changing default width or any threshold constant

## Decisions

**`COLUMNS` first**: Claude Code's allocated width is the correct answer. No subprocess or file read can be more authoritative. Move the `os.environ.get('COLUMNS')` block to position 1.

**tmux stays second** (after COLUMNS): The tmux width is useful for users who run the statusline outside Claude Code. It must be after `COLUMNS` so Claude Code's value wins.

**`timeout=0.2`**: 200 ms is enough for a healthy tmux to respond and negligible for a normal render cycle. On timeout, `subprocess.run` raises `subprocess.TimeoutExpired`; add it to the existing except clause.

## Risks / Trade-offs

- Users who rely on a tmux-set width and also have `COLUMNS` set to something else (unusual) will now see `COLUMNS`. This is the correct behaviour since `COLUMNS` is set by the calling process.
- 200 ms timeout may be tight on extremely slow systems; the fallback chain still resolves width from other sources.
