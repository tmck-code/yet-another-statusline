## Why

The wide top-row session timer shows elapsed time for the whole session (`cost.total_duration_ms`), which keeps counting across a `/clear`. After a `/clear` the conversation context is reset but the session-wide clock gives no sense of how long the *current* (post-clear) working context has been running. Adding a "since last `/clear`" timer restores that signal without losing the whole-session view.

## What Changes

- Add a second timer to the wide top-row elapsed section: **time since the most recent `/clear`** in the current transcript.
- Detection: a `/clear` forks a new transcript file (new `session_id`) and writes a `<command-name>/clear</command-name>` user marker near the top. The current transcript therefore contains **at most one** such marker. A new gather field reads its `timestamp` via a **bounded head-scan** (first ~30 lines) so fresh sessions and large transcripts never pay a full-file scan.
- Display rules (wide layout only — narrow/medium are unaffected):
  - **Fresh session** (no `/clear` marker) → render the existing session timer unchanged (byte-identical to today).
  - **Cleared session** → show the clear timer (glyph + accent colour) **first/leftmost**, then the session timer (bare grey), inside the single existing elapsed cell.
  - **Degradation ladder:** path protection stays the outermost guard (the whole elapsed cell still sheds if the path would drop below 5 visible columns); within the cell, if both timers don't fit, prefer the clear timer alone over the session timer.
- The clear timer reuses `_fmt_elapsed_clock` (`MM:SS` / `H:MM:SS`) and is computed wall-clock as `now − clear_epoch`, clamped at 0 for clock skew.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `statusline-info`: add a render-independent `SessionView` gather field exposing the most-recent `/clear` epoch (or `None`) from a bounded head-scan of the current transcript.
- `top-row-format`: the wide elapsed section gains an optional second (since-`/clear`) timer with clear-first ordering, a distinguishing glyph + accent colour, and a both → clear-only → shed degradation ladder; the fresh-session single-timer rendering is preserved unchanged.

## Impact

- `claude/yas/info/` — new bounded head-scan reader for the `/clear` marker timestamp.
- `claude/yas/info/__init__.py` — new `@cached_property` on `SessionView`.
- `claude/yas/renderer.py` — `elapsed_section` composes one or two timers; new glyph/accent colour.
- `claude/yas/constants.py` — new Nerd Font glyph constant for the clear timer.
- `claude/yas/layout.py` — `build_wide` threads the clear timer and the both → clear-only → shed width ladder through the existing elapsed cell (single divider/elbow unchanged).
- Tests under `test/` (model/section, layout seam, info) and `CONTEXT.md` glossary if a new displayed term is introduced.
