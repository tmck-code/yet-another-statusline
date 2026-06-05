## Context

`context_line()` and `context_line_compact()` in `renderer.py` compute the fill ratio as `(total_input_tokens + total_output_tokens) / soft_limit`. Claude Code's own `/context` panel uses input-only tokens and provides a pre-calculated `context_window.used_percentage` field on the stdin payload. The mismatch means the statusline can show a noticeably different percentage than the authoritative source.

`ContextWindow.used_percentage` is already parsed into `session.py:214` and available on the `ctx` argument passed to both helpers; it just isn't used.

## Goals / Non-Goals

**Goals:**
- Display a context percentage that matches Claude Code's `/context` panel
- Use the host-supplied `used_percentage` when present (avoids any rounding mismatch)
- Fall back to an input-only manual calc (`total_input_tokens / context_window_size`) when `used_percentage` is `None`
- Clamp negative values to zero

**Non-Goals:**
- Changing the visual layout, bar shape, or surrounding labels
- Altering how `soft_limit` is resolved (unchanged)

## Decisions

**Primary source — `ctx.used_percentage`**: The host pre-calculates this value using the same logic as `/context`. Prefer it to avoid any divergence.

**Fallback — input-only manual calc**: When `used_percentage` is `None` (older Claude Code versions that don't emit the field), compute `ctx.total_input_tokens / ctx.context_window_size` (not soft_limit, to stay consistent with the input-only intent). Guard against `context_window_size == 0`.

**Remove output tokens from numerator**: `total_output_tokens` is not counted by Claude Code's context panel. Removing it from both the fill ratio and the displayed percentage eliminates the discrepancy.

**`soft_limit` as the bar's visual ceiling stays unchanged**: The bar still fills to 100% at `soft_limit` tokens, capped at the model window. Only the percentage label source changes.

## Risks / Trade-offs

- Users on older Claude Code builds (pre-`used_percentage` field) will see the fallback calculation. The fallback is more correct than the current formula even without the host field.
- Snapshot baselines that include a context row will shift and need re-baselining.
