## Why

The context bar and percentage shown in the statusline are calculated as `(total_input_tokens + total_output_tokens) / soft_limit`, which diverges from what Claude Code's own `/context` command displays. Claude Code tracks context fill as input-only and provides a pre-calculated `context_window.used_percentage` on the stdin payload; the statusline should prefer that authoritative value rather than recomputing it incorrectly.

## What Changes

- `context_line()` and `context_line_compact()` in `renderer.py` will use `ctx.used_percentage` (the host-provided value) as the primary source for the fill ratio and the displayed percentage, falling back to an input-only manual calculation (`total_input_tokens / context_window_size`) when `used_percentage` is `None`.
- Output tokens will no longer be added to the numerator of the context fill calculation.
- Negative fill ratios will be clamped to zero.
- Snapshot baselines that include a context row will be re-baselined.

## Capabilities

### New Capabilities

- `context-percentage-accuracy`: The context bar fill ratio and the displayed `%` figure match what Claude Code's `/context` panel shows — input-only, host-calculated when available.

### Modified Capabilities

*(none — this is a correctness fix to an existing renderer helper, not a spec-level interface change)*

## Impact

- `claude/yas/renderer.py`: `context_line`, `context_line_compact` methods
- `claude/yas/session.py`: `ContextWindow.used_percentage` field (already parsed; newly consumed)
- Tests: any snapshot or assertion that pins the context percentage value will need re-baselining
