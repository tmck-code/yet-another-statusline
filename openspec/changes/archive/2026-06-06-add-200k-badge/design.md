## Context

`SessionInfo.exceeds_200k_tokens` is parsed from the stdin payload (`session.py:270`) but never consumed by the renderer. The context bar's fill ratio is relative to `soft_limit` (typically 150 k), so on a 1 M+ context window a user can be at 300 k tokens (30% fill, no visual alarm) while compaction pressure is already building past the 200 k boundary.

The badge must fit inside the context row without breaking the bar-width arithmetic. Both `context_line` and `context_line_compact` in `renderer.py` compute `filled = int(fill_ratio * bar_w)` where `bar_w` is derived from `available` minus prefix length. Adding the badge reduces `available` by the badge's visible width.

## Goals / Non-Goals

**Goals:**
- Render a compact `!200K` badge in the context row when `exceeds_200k_tokens` is true
- Render the badge in a warning colour (amber/yellow) visually distinct from the fill bar
- Reduce `bar_w` by the badge's visible width to prevent overflow
- Emit nothing (zero width) when `exceeds_200k_tokens` is false

**Non-Goals:**
- Changing the bar fill ratio or percentage label logic (handled by fix-context-percentage)
- Adding a separate row or popup for the alert

## Decisions

**Badge string**: `'!200K'` — 5 visible characters. Rendered as `{AMBER_CLR}!200K{RESET}` where `AMBER_CLR` is a new constant in `constants.py` if not already present (check `CLR_YELLOW` / `CLR_ORANGE` first before adding).

**Placement**: prepended to the context row, before the token count prefix, separated by a space. Total overhead when active: `len('!200K') + 1 = 6` visible columns subtracted from `bar_w`.

**`available` threading**: both `context_line(ctx, available, soft_limit)` and `context_line_compact(ctx, available, soft_limit)` accept `available` as a parameter. The badge-width deduction happens inside the helper, keeping the caller unchanged.

**Callers pass `session.exceeds_200k_tokens`**: add it as a boolean keyword argument (default `False`) to both helpers so existing call sites are unaffected.

## Risks / Trade-offs

- Very narrow terminals may squeeze the bar to zero columns when the badge is active. The existing bar-width floor (`max(bar_w, 0)`) already handles this gracefully.
- The badge colour constant may need to be added to `constants.py`; verify no existing amber/yellow constant matches before adding.
