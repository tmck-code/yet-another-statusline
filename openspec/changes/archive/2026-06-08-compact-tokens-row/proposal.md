## Why

The tokens/cost row (the wide layout's "3rd row", `Renderer.tokens_cost`) is two
terminal lines tall: session figures stacked over day figures, with a 2-row-tall
sparkline drawn from "Symbols for Legacy Computing" half-block glyphs (U+1FBxx)
that render inconsistently across fonts and span 120s of history. Collapsing it to
a single line reclaims a full row of vertical space in every wide render and lets
the live rate sparkline use the well-supported block elements (U+2581–U+2588).

## What Changes

- Collapse the tokens/cost row from two content lines to **one**. Session and day
  figures merge per field as `session/day`:
  - tokens: `↓ 128.4K/1.9M (1.2M/18.3M) ↑ 47.3K/612.5K` — input, paired cache in
    parentheses, output; each `session/day`.
  - cost: `$3.27 / $41.88` — session cost / day cost.
  - rate + sparkline: `󱢧 2.3K t/m ▂▃▄▅…` — unchanged rate label, single-row spark.
- Replace the 2-row half-block sparkline (`SPARK_RISE_*` / `SPARK_FALL_*`, U+1FBxx)
  with a **single-row, 8-level block-element sparkline** (` ▁▂▃▄▅▆▇█`, U+2581–U+2588),
  coloured by height ratio as today.
- The sparkline reads the **last 60s** of token-rate history (`TokenRate.WINDOW`)
  instead of today's `TokenRate.WINDOW * 2` (120s).
- Keep the row's three-column structure (tokens │ cost │ rate+spark) with matching
  `┬`/`┴` elbows on the borders above and below — now over one content row.
- Add a `show_day_stats` knob (env `YAS_SHOW_DAY_STATS=0`, `[tokens]
  show_day_stats = false`; default **on**). When disabled, the row drops every day
  figure and renders session-only: `↓ 128.4K (1.2M) ↑ 47.3K │ $3.27 │ 󱢧 2.3K t/m …`.

## Capabilities

### New Capabilities
- `compact-tokens-row`: the single-line tokens/cost/rate row — the `session/day`
  slash-merged token and cost format, the paired cache parenthetical, the
  single-row block-element sparkline over a 60s window, the three-column elbow
  structure, and the day-stats-disabled session-only variant.

### Modified Capabilities
- `statusline-config`: add a seventh knob `show_day_stats` (canonical
  `YAS_SHOW_DAY_STATS`, `[tokens].show_day_stats`), default `true`, resolved through
  the existing precedence chain and fail-safe validation (boolean; env form treats
  any non-empty value as true, `0`/`false`/`no` as false).

## Impact

- `claude/yas/renderer.py` — `tokens_cost` returns a single content line; new
  session/day merge + paired-cache formatting; `show_day_stats` branch.
- `claude/yas/render/gradient.py` — new single-row block sparkline on
  `GradientEngine`; the 2-row `_spark_rise/_spark_fall/_spark_flat` path and the
  `SPARK_RISE_*`/`SPARK_FALL_*` constants in `constants.py` are removed if unused.
- `claude/yas/layout.py` — `build_wide` threads one tokens line and its elbow
  columns (`vsep_cols`, `spark_mark_col`) for a single row instead of two.
- `claude/yas/config.py` + `constants.py` — `show_day_stats` field, default,
  env/toml resolution, validation.
- `CONTEXT.md` — glossary update if any displayed term changes.
- Tests: `test_tokens_cost.py`, `test_gradient_math.py`, `test_config.py`,
  `test_layout_seam.py`.
- Prototype `ops/proto_compact_tokens_row.py` (+ NOTES) is deleted once applied.
