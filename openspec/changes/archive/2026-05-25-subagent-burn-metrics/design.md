## Context

`claude/statusline_command.py` already renders a per-subagent row via `Renderer.subagent_row` (~L2064). Each `RunningSubagent` (~L870) carries `billed_in`, `cache_read_in`, `output`, `total_input` (= `billed_in + cache_read_in`), `first_timestamp`, `model`, and `last_activity`. The wide branch (`width > 100`) draws two lines; the narrow branch collapses to one. The main session's cumulative usage is available in `build_wide` as `usage = TranscriptUsage.from_transcript(...)` (~L2619).

The main-row token rate (`tok_rate`, `TokenRate`, ~L621) is a live 60s-window delta persisted to `statusline-token-rate.log`, sampled once per render. The 5h/7d rate-limit "burndown" trend (`burndown_trend`, ~L2441) compares an account-wide `used_percentage` against an ideal linear pace; that percentage is opaque (no tokens→% factor) and account-wide, so it cannot be attributed to an individual subagent.

PUA (Nerd Font) glyphs must be hoisted to module-level escape constants before any line containing them is edited (skill PUA refactor rule); width math must use `_visible_width`, never `len`.

## Goals / Non-Goals

**Goals:**
- Show, per wide subagent row, a cumulative **average t/m** (`(total_input + output) / duration_min`) and a **session token-share %** (`sub_inout / (main_inout + Σ subagent_inout)`).
- Make "which subagent dominates the session's burn" scannable via a magnitude-mapped colour on the share.
- Degrade gracefully: omit (not zero) figures in degenerate cases; drop the pair atomically when cramped.
- Keep the change additive — no new persisted state, no new runtime dependency.

**Non-Goals:**
- No per-subagent attribution of the 5h/7d rate-limit burndown delta (not computable — see Context).
- No live recent-window token rate per subagent (subagents are too short-lived, `STALE_SECONDS = 20`, to sample reliably).
- No change to the narrow (≤100-col) subagent collapse.
- No change to the main row, token-rate log, or rate-limit rendering.

## Decisions

**D1 — Throughput basis is in+out cumulative average, not a live window.**
`(total_input + output) / duration_min`. Rationale: matches the main row's in+out t/m meaning so "t/m" reads identically everywhere; cumulative is computable from data already on `RunningSubagent` with no new persistence. Alternatives: live 60s window (rejected — needs new per-subagent sample log and is near-always empty for short-lived agents); output-only or input-only (rejected — would diverge from the main row's combined t/m and invite misreads).

**D2 — Share denominator is main + all subagents.**
`session_inout = main_inout + Σ subagent_inout`, with `main_inout = (usage.billed_in + usage.cache_read) + usage.out`. Rationale: makes "share of session" literal and mutually consistent (main + all subagent shares sum to 100%). Alternatives: subagents-only denominator (rejected — hides how much the main thread burned); ratio-vs-main (rejected — can exceed 100%, reads oddly). The main and subagent transcripts are disjoint (subagents are separate sidechains), so summing is correct, not double-counting.

**D3 — Denominator computed once in the builder, passed into `subagent_row`.**
`build_wide` computes `session_inout` from `usage` plus the already-loaded `subagents` list and passes it as a new `session_inout` argument to `subagent_row`. `build_medium` / `build_narrow` pass it through (or pass it but never render the cluster). Rationale: avoids recomputing the sum per row and keeps `subagent_row` a pure function of its inputs.

**D4 — Glyphs: reuse `ICON_TOK_RATE` for t/m, add `GLYPH_PIE = '\uf200'` for share.**
Hoist `GLYPH_PIE` (nf-fa-pie_chart) to module scope alongside `ICON_COST`/`GLYPH_MODEL` per the PUA rule. Rationale: gauge glyph keeps t/m consistent with the main row; a distinct glyph for share aids scanning.

**D5 — Colour: t/m flat (`self.TOK`), share gradient by magnitude.**
Share uses the existing fill gradient keyed on the share fraction (domain is a natural 0–1), so the dominant agent glows hot. t/m has no principled ceiling, so it stays flat. Alternative (gradient t/m) rejected for lack of a meaningful max.

**D6 — Degenerate handling: omit, don't fake.**
Avg t/m omitted when `duration < 3s` or `first_timestamp == 0`; share omitted when `session_inout == 0`. Rationale: mirrors `burndown_delta` returning `None` during warmup rather than printing garbage; a 3s floor kills the first-second division spike. Omitting (vs. zeroing) avoids implying a busy young agent is idle.

**D7 — Atomic, pad-based responsive drop, wide-row-only.**
Build the line-2 right cluster with the figure pair; if appending them would push `pad2` below its minimum gap (2 cols), omit both and fall back to `⧗tok · $cost`. Never render one without the other. The narrow branch never renders the pair. Rationale: matches the row's existing `pad2 = max(1, …)` computation; partial states look broken.

## Risks / Trade-offs

- **Cumulative average masks bursty behaviour** → Accepted as the deliberate trade for not adding a live-sample log (D1); a long-idle agent reads as low t/m, which is truthful for a *cumulative* average and labelled as such by the shared t/m semantics.
- **`GLYPH_PIE` lost through a chat/Edit round-trip** → Mitigated by hoisting to a `'\uf200'` escape constant before editing any line that references it (D4 / PUA rule).
- **Width miscalculation crooks the box** → Mitigated by computing cluster width with `_visible_width` (never `len`) and reusing the row's existing pad math (D7); covered by a boundary test.
- **Double-counting main vs. subagent tokens** → Not a risk: main and subagent transcripts are disjoint sidechains (D2).
- **`build_medium` / `build_narrow` signature drift** → Mitigated by threading `session_inout` through all callers in one change and asserting via the demo across narrow→medium→wide thresholds.
