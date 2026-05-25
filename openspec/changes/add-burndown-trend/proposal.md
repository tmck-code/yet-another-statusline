## Why

The statusline shows current rate-limit usage (`<pct>% T-<delta>`) but gives no signal about *velocity* — whether the user is on track to hit the cap before the window resets, or coasting well under quota. A user at 60% with 2.5 hours left looks identical to a user at 60% with 30 minutes left, even though the first is on-pace and the second is burning unsustainably fast. Surfacing a burndown trend lets the user catch runaway usage early (sub-agent spam, runaway loops) before they hit the limit.

## What Changes

- Add a **Burndown Trend** indicator to the wide and medium layouts, rendered alongside each rate-limit percentage.
- For each active rate-limit bucket (5h and 7d), compute the delta between actual `used_percentage` and the ideal linear burn at the current point in the window.
- Render the delta as `▲<abs>%` (over-burn, red ramp), `▼<abs>%` (under-burn, green ramp), or `·` (on-pace, within ±0.5%). Magnitude-ramped colour with stepped buckets at 5% / 15%, symmetric across direction.
- Suppress the indicator when `resets_at == 0`, when `resets_at` is in the past, and during the window's warmup period (first 5 min of 5h, first 30 min of 7d) to avoid noise.
- Wide layout shows trend for both 5h and 7d; medium shows 5h only; narrow shows nothing (consistent with existing graceful degradation).
- Update CONTEXT.md: add **Burndown Trend** to the glossary, fix the stale claim that Seven-Day Limit is "parsed but not rendered" (it is rendered today).

## Capabilities

### New Capabilities

- `rate-limit-burndown`: Velocity-vs-quota indicator for rate-limit buckets — formula, suppression rules, colour buckets, and per-layout rendering policy.

### Modified Capabilities

<!-- None: no existing specs in openspec/specs/. -->

## Impact

- **Code**: `claude/statusline_command.py` — new pure-math helper (`burndown_delta`), new `Renderer.burndown_trend` method, threaded into `Renderer.helper`, `Renderer.model_right_section`, and `Renderer.model_right_section_compact`. New module-level constants `FIVE_HOUR_MINUTES`, `SEVEN_DAY_MINUTES`, warmup constants.
- **Tests**: new `test/test_burndown.py` for pure math; additions to `test/test_helper.py` and `test/test_model_section.py` for integration.
- **Docs**: `CONTEXT.md` — new glossary entry and stale-line fix.
- **No new dependencies.** No data-model changes to `RateBucket` or `SessionInfo` (everything derivable from existing `used_percentage` + `resets_at`).
- **No breaking changes.** The indicator is additive; suppressing it for stale data preserves existing behaviour.
- **Multi-session observer (`claude/mon.py`)**: the trend renders automatically because it's threaded through existing helpers; dim post-processing washes over it acceptably. Documented as known minor limitation; not addressed in this change.
