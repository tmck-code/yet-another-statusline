## Context

The statusline renderer (`claude/statusline_command.py`) already consumes `rate_limits.five_hour` and `rate_limits.seven_day` from Claude Code's session JSON. Each bucket carries `used_percentage` and `resets_at` (unix timestamp of the next reset). The existing display:

- `Renderer.helper()` formats the 5h bucket as `<pct>% T-<delta>`.
- `Renderer.model_right_section()` (wide) appends 7d as `| <pct>%`.
- `Renderer.model_right_section_compact()` (medium/narrow) shows 5h only as `<pct>% <h>m`.

The renderer is layered: pure math in `GradientEngine`, border math in `BorderRenderer`, section composition in `Renderer`. Tests live under `test/` partitioned by layer (`test_pure_helpers.py`, `test_helper.py`, `test_model_section.py`, etc.). All width math goes through `_visible_width` (ANSI-stripping, wide-char-aware).

The trend feature derives a new value from existing inputs — no new fields on `RateBucket`, no schema change, no upstream API change. The math is pure given `(used_percentage, resets_at, now, window_minutes, warmup_minutes)`.

## Goals / Non-Goals

**Goals:**

- Make velocity legible at a glance: a user mid-window can tell whether they are on track, ahead, or burning too fast for the remaining window.
- Keep the indicator additive and non-disruptive — when data is stale or noisy (no window, expired window, fresh window warmup), suppress rather than misinform.
- Preserve existing graceful-degradation across narrow → medium → wide layouts.
- Stay within the existing renderer architecture: pure math in a module-level helper, presentation on `Renderer`.

**Non-Goals:**

- **Per-subagent burn rates** — the original feedback bundles this with the trend ask, but subagent velocity is a separate signal with a different data source (`RunningSubagents` aggregations) and a different display surface (subagent rows). Out of scope for this change.
- **Real-time cache countdown** — the original feedback is ambiguous (Anthropic prompt-cache TTL? 5h window cache reset?) and needs its own grilling round. Out of scope.
- **Context-window burndown** — the context window has no time dimension, so the same formula doesn't apply.
- **Continuous-gradient colouring** — the renderer's existing fill helpers (`fill_colour`, `risk_zone_color`) use stepped buckets, and we match that aesthetic.
- **Fixed-width indicator** to prevent jitter — existing `<pct>%` already varies width (2–4 cols) and this hasn't caused layout problems; not adding complexity here.

## Decisions

### Decision 1 — Derive `elapsed_minutes` from `resets_at` and a window constant

```
window_start_ts  = resets_at - window_minutes * 60
elapsed_minutes  = (now - window_start_ts) / 60
ideal_pct        = (elapsed_minutes / window_minutes) * 100
delta            = used_percentage - ideal_pct       # +ve = over-burn
```

Window constants are hard-coded at module scope: `FIVE_HOUR_MINUTES = 300`, `SEVEN_DAY_MINUTES = 10080`.

**Alternatives considered:**

- *Have the upstream JSON include `started_at`* — would remove guesswork but requires an Anthropic-side change we don't control.
- *Derive `window_minutes` from `(now - resets_at)` plus heuristics* — fragile; can't disambiguate 5h-window-just-reset from 7d-window-near-end.

Hard-coded constants are honest about the dependency: if Anthropic changes the plan structure, we update one line.

### Decision 2 — Suppression rules (no indicator shown)

The indicator returns an empty string under any of:

1. `resets_at == 0` (no active window — matches existing `∞` semantics in `helper()`).
2. `now >= resets_at` (window already expired — `helper()` shows `∞` here too).
3. `elapsed_minutes < warmup_minutes` (fresh window, denominator too small to be informative).

Warmup constants: `FIVE_HOUR_WARMUP_MINUTES = 5`, `SEVEN_DAY_WARMUP_MINUTES = 30`.

**Alternatives considered:**

- *Show the indicator unconditionally* — produces noisy `▲` flickering on the first prompt of every fresh window. Trains users to ignore it.
- *Clamp `ideal_pct` to a floor* — distorts the math; users would reasonably expect the trend to be exact.

Suppression is the honest signal: "not enough data yet."

### Decision 3 — Format and on-pace dot

Format: `▲<abs>%` (over-burn) or `▼<abs>%` (under-burn). One decimal place. Sign is implied by the arrow.

When `|delta| ≤ 0.5%`, render `·` (middle dot) instead of an arrow. This avoids the visual noise of `▲0.0%` flickering between directions at the on-pace threshold.

**Alternatives considered:**

- *Keep the negative sign in the down-arrow case* (matches the original spec literally) — redundant double-encoding with the arrow.
- *Integer percent* — loses signal at small but real deltas.
- *Suppress entirely at on-pace* — leaves a hole in the row that flickers in and out.

### Decision 4 — Stepped, symmetric, magnitude-ramped colour buckets

Three intensity buckets per direction, same cutoffs for both:

| `|delta|`        | `▲` colour          | `▼` colour              |
|------------------|---------------------|-------------------------|
| 0.5 – 5 %        | `self.safe` (dim)   | `self.safe` (dim green) |
| 5 – 15 %         | `self.warn`         | mid green               |
| ≥ 15 %           | `self.alert`        | bright green            |
| ≤ 0.5 %          | `·` in dim grey     | (same)                  |

Same intensity structure across both directions; hue differs. Re-uses the existing `Renderer.fill_colour` palette where possible to avoid introducing new colour state.

**Alternatives considered:**

- *Asymmetric ramps* (no "alert" green at the top end) — more semantically accurate (deep under-burn isn't alarming) but adds branching and a special-case green palette.
- *Continuous interpolation* — matches the rainbow border aesthetic, but inconsistent with `fill_colour`/`risk_zone_color`. More code, no clear win.
- *Match the `%` colour* — loses the velocity signal whenever the absolute usage is high.

### Decision 5 — Implementation seam: pure math + Renderer method

```python
# Module-level (pure, no Renderer/ANSI state)
def burndown_delta(used_pct: float, resets_at: int, window_minutes: int,
                   warmup_minutes: int, now: float | None = None) -> float | None:
    """Returns delta in percentage points, or None to suppress."""

# Renderer method (presentation, picks colour buckets + glyphs)
def burndown_trend(self, used_pct: float, resets_at: int,
                   window_minutes: int, warmup_minutes: int) -> str:
    """Returns ANSI-formatted fragment, or '' when suppressed."""
```

The pure helper is testable in `test_burndown.py` without ANSI noise. The Renderer method is tested through `test_helper.py` and `test_model_section.py` using the existing `strip_ansi` helper.

**Alternatives considered:**

- *Single bundled method on `Renderer`* — couples math to presentation, harder to test.
- *Dataclass (`BurndownTrend`) carried through `RowSpec`* — overengineered for one indicator. The trend is rendered inline in a content row; it doesn't drive layout decisions.

### Decision 6 — Per-layout policy

- **Wide:** trend for both 5h and 7d. Position: between `<pct>%` and the countdown. New format for 5h: `<pct>% <trend> T-<delta>`. New format for 7d: `<pct>% <trend>`.
- **Medium:** trend for 5h only (matches the existing pattern where 7d is dropped from compact).
- **Narrow:** no trend (matches existing pattern where countdown is the only adornment).

This matches the existing "drop adornments outermost-first" degradation rule.

### Decision 7 — `now` injection for tests

`burndown_delta` accepts `now: float | None = None`, defaulting to `time.time()` when omitted. Tests pass a fixed `now`. No freezegun-style monkey-patching needed.

## Risks / Trade-offs

- **Risk:** Width jitter as the trend digit count changes (e.g. `▲4.9%` → `▲14.0%` adds one column) → Mitigation: existing `<pct>%` already varies the same way; layout has tolerated this for the lifetime of the renderer. No fix needed.
- **Risk:** `mon.py`'s dim post-processing washes the velocity-bucket colours, undermining the signal on inactive sessions → Mitigation: accept. Dim sessions are inactive by definition; the trend isn't actionable there. Document as a known minor limitation.
- **Risk:** First-prompt-of-window flicker on the 7d bucket lingers longer than 5h because the bucket's `used_percentage` updates on every request (so even after warmup, the first hour can show large `▲` deltas) → Mitigation: 30-min warmup absorbs the worst of it. After warmup the math is correct — a sustained big-▲ early in the week genuinely is over-pace, and that *is* the signal we want.
- **Risk:** Hard-coded window constants drift if Anthropic changes plan structure → Mitigation: constants live at module scope with comment pointing at the source of truth. Change is one-line if needed.
- **Trade-off:** Symmetric colour intensity (chosen) treats deep ▼ as visually "loud" even though it's good news. Asymmetric (rejected) would be more semantically faithful. Chose symmetric for simplicity; if user feedback says deep-green is jarring we can revisit.
