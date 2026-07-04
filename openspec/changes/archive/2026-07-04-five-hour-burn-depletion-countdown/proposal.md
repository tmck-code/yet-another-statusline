## Why

The wide top row's 5-hour segment shows *when the window resets* (`(-H:MM)`) and a `+X.X%` burndown *deviation* glyph, but nothing that answers the operationally urgent question: **at the current burn rate, when do I actually run out?** The deviation is a pace-vs-ideal signal, not a rate, so a user burning fast has no direct read on time-to-depletion. Surfacing a second, danger-coloured countdown next to the reset countdown makes an imminent lockout legible before it happens.

## What Changes

- Add a **second countdown** beside the existing 5-hour reset countdown in the wide top-row 5-hour segment. Rendered as one parenthesised group: `(-{h}:{m:02d}/-{dh}:{dm:02d})`, e.g. `(-0:11/-0:04)` = "window resets in 11 min, but tokens deplete in 4 min at the current burn rate".
- Introduce an **instantaneous burn-rate model**: sample the 5-hour `used_percentage` over time and compute `rate = Δused% / Δt` (%/min) first-vs-last over a short lookback window. This is explicitly **not** the existing `burndown_delta` deviation, which must not be reused as a rate.
- Add a new on-disk sampler `FiveHourRate` (mirroring `TokenRate`) writing a **global** series (not keyed by `session_id`, since the 5-hour `used_percentage` is account-wide) to a new log under `CLAUDE_DIR`. Samples are filtered to the current `resets_at` so a window rollover starts a fresh series.
- Add a new pure depletion helper in `render/metrics.py`: `deplete_min = (100 - used_pct) / rate`.
- Add a config knob `[tokens].five_hour_rate_window` (mirroring `token_window`) controlling the lookback, default `300` seconds (~5 min), plus a small `DT_FLOOR` guard constant for the minimum sample span.
- Show the depletion segment **only** when the account is actually burning toward a lockout: `rate > 0` AND `deplete_min < remain_min` AND there are ≥2 valid samples spanning ≥ `DT_FLOOR`; otherwise render exactly today's `(-{h}:{m:02d})`. The depletion segment is drawn in a WARN colour so it reads as a danger signal.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `top-row-format`: the 5-hour reset-countdown requirement gains an optional second depletion countdown fed by a new instantaneous burn-rate estimate; the estimate's sampling, gating, format, and colour are specified. The existing single-countdown rendering is preserved byte-identically when the depletion segment is suppressed.
- `statusline-config`: add a `five_hour_rate_window` knob (env `YAS_FIVE_HOUR_RATE_WINDOW` / legacy `STATUSLINE_FIVE_HOUR_RATE_WINDOW`, `[tokens].five_hour_rate_window`, default `300`) governing the burn-rate lookback window.

## Impact

- `claude/yas/tokens.py` — new `FiveHourRate` sampler (mirrors `TokenRate`); new `five_h_rate` slot on `TickRecord`.
- `claude/yas/render/metrics.py` — new pure `deplete_minutes` helper beside `burndown_delta`.
- `claude/yas/config.py` — new `five_hour_rate_window` field / `__slots__` / default-arg / `_resolve` wiring; new `DEFAULT_FIVE_HOUR_RATE_WINDOW`.
- `claude/yas/constants.py` — new `DT_FLOOR` guard constant.
- `claude/yas/app.py` — `record_tick` calls `FiveHourRate.update` and stores the result on `TickRecord`.
- `claude/yas/layout.py` + `claude/yas/renderer.py` — thread `five_h_rate` from `build_wide` → `model_right_section` → `_rate_helpers` → `helper`; compose the depletion segment.
- `README.md` — new knob-table row and `[tokens]` example entry.
- Tests under `test/` (`test_helper.py`, `test_burndown.py`, `test_config.py`) and `CONTEXT.md` glossary for the new displayed term.
