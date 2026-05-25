## Why

The statusline shows per-subagent tokens, cost, and duration, but not how fast each subagent is burning tokens or how much of the session's total token spend it accounts for. When several subagents run concurrently, there is no way to see which one dominates the session's burn at a glance.

## What Changes

- Add two per-subagent figures to the **wide** subagent row (terminal width > 100):
  - **avg t/m**: cumulative average token throughput — `(total_input + output) ÷ duration_minutes`.
  - **session share %**: this subagent's fraction of the whole session's token spend — `sub_inout ÷ (main_inout + Σ subagent_inout)`.
- Append both to the line-2 right cluster after `⧗tok · $cost`, rendered as `· {gauge} 30 t/m · {pie} 28%`.
- Drop the pair atomically when there is not enough horizontal room (pad-based), falling back to the existing `⧗tok · $cost`.
- Omit a figure in degenerate cases: avg t/m omitted when `duration < 3s` or `first_timestamp == 0`; share omitted when the denominator is `0`.
- Colour: avg t/m flat (`self.TOK`, matching the main row's t/m); session share gradient-mapped by magnitude so the dominant agent glows hot.
- Wide-row-only: the narrow single-line subagent collapse (width ≤ 100) is unchanged.

Explicitly **not** included (rejected during design):
- Per-subagent attribution of the 5h/7d rate-limit burndown delta — impossible: no tokens→% factor is exposed, the rate-limit window is account-wide, and the delta is not a per-agent additive quantity.
- A live recent-window token rate per subagent — subagents are too short-lived (`STALE_SECONDS = 20`) to gather ≥2 samples reliably, so it would be near-always empty.

## Capabilities

### New Capabilities
- `subagent-burn-metrics`: per-subagent average token throughput (t/m) and session token-share (%) on the wide subagent row, including their computation basis, degenerate-case handling, responsive drop behaviour, glyphs, and colour rules.

### Modified Capabilities
<!-- None: no existing specs in openspec/specs/. -->

## Impact

- `claude/statusline_command.py`:
  - New module-level glyph constant `GLYPH_PIE = '\uf200'` (nf-fa-pie_chart), hoisted per the PUA refactor rule.
  - `Renderer.subagent_row` gains a `session_inout` argument and renders the two figures in the `width > 100` branch only.
  - `build_wide` computes the session denominator (`main_inout + Σ subagent_inout`) once and threads it into `subagent_row`; `build_medium` / `build_narrow` pass it through without rendering the cluster.
- Tests: new coverage for the avg-t/m and share math, degenerate-case omission, and the atomic pad-drop boundary.
- `CONTEXT.md`: glossary entries for the two new displayed terms.
- No new runtime dependencies; no persisted state added.
