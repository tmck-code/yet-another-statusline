## Why

Claude Code sets `exceeds_200k_tokens: true` on the stdin payload when the context window has grown past 200 k tokens. The field is already parsed into `SessionInfo`, but the renderer never surfaces it. On standard 200 k windows the context bar already fills near 100%, so the alert is redundant — but on 1 M+ windows, 200 k tokens is only ~20% fill and the bar gives no visual warning that compaction pressure is building. A compact badge (`!200K`) in the context row makes this threshold visible at any window size.

## What Changes

- When `session.exceeds_200k_tokens` is `True`, a compact `!200K` badge is prepended to the context row in all layouts (narrow, medium, wide).
- The badge is rendered in a warning colour (amber/yellow) distinct from the normal context fill colour.
- The bar width is reduced by the badge width to prevent overflow.
- The badge is absent (zero width) when `exceeds_200k_tokens` is `False`, so existing layouts are unaffected.

## Capabilities

### New Capabilities

- `exceeds-200k-badge`: A visible `!200K` alert badge appears in the context row whenever `exceeds_200k_tokens` is true, regardless of the bar's fill level.

### Modified Capabilities

*(none — purely additive; the badge occupies reserved space only when active)*

## Impact

- `claude/yas/renderer.py`: `context_line`, `context_line_compact`
- `claude/yas/session.py`: `SessionInfo.exceeds_200k_tokens` (already parsed; newly consumed)
- `claude/yas/constants.py`: may need a new colour constant if amber is not already defined
- Tests: `test_context_line.py` — new scenario for badge presence/absence; bar-width assertions will need updating when badge is active
