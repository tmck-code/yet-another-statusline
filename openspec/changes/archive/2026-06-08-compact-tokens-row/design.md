## Context

The wide layout's tokens/cost row is produced by `Renderer.tokens_cost`
(`claude/yas/renderer.py`), which returns **two** content lines:

- line 1 — session `↓ in (cache) ↑ out` │ session cost │ rate label + sparkline **top** half
- line 2 — day `↓ in (cache) ↑ out` │ day cost │ (blank) + sparkline **bottom** half

The two-row height has two independent causes: (a) session figures are stacked
over day figures, and (b) the sparkline is two rows tall, built from "Symbols for
Legacy Computing" half-block rise/fall glyphs (`SPARK_RISE_*` / `SPARK_FALL_*`,
U+1FBxx) via `GradientEngine._spark_rise/_spark_fall/_spark_flat` and `sparkline`.
The history window is `TokenRate.WINDOW * 2` (120s) at the `tokens_cost` call site.

`build_wide` (`claude/yas/layout.py`) consumes `tokens_cost`'s
`(line_tokens, vsep_cols, spark_mark_col)` triple: it threads `vsep_cols` as the
elbow columns on the separator above, appends each line of `line_tokens` as a
`content` row, and uses `spark_mark_col` for the 60s tick marker. A throwaway
prototype (`ops/proto_compact_tokens_row.py`) validated three single-line shapes;
the chosen shape is the `session/day` slash-merge with a paired cache parenthetical.

The config layer (`claude/yas/config.py`, `Config` frozen dataclass) resolves six
knobs through CLI → `YAS_*` env → legacy alias → `yas.toml` → default, with
fail-safe validation and a config-error row. `token_window` already defaults to 60.

## Goals / Non-Goals

**Goals:**
- Collapse the tokens/cost row to a single content line in the wide layout.
- Merge session and day figures as `session/day` per field, with paired cache.
- Replace the 2-row legacy-glyph sparkline with a 1-row block-element sparkline
  (` ▁▂▃▄▅▆▇█`) over a 60s window.
- Add a `show_day_stats` knob (default on) that drops day figures when off.
- Keep the three-column elbow alignment exact (every `│` ↔ `┬`/`┴`).

**Non-Goals:**
- Changing the narrow/medium layouts (they do not render `tokens_cost`).
- Changing token-rate accounting, cost math, or the on-disk rate log format.
- Reworking the gradient/colour stops or the rate label glyph.
- A per-model or CLI form of `show_day_stats` (env + toml only, like other knobs).

## Decisions

**D1 — `tokens_cost` returns a one-element line list.** Keep the existing return
shape `(list[str], (col1, col2), mark_col)` so `build_wide` keeps threading
`vsep_cols`/`spark_mark_col` unchanged, but the list has length 1. Rationale: the
builder's elbow-threading and seam logic already iterate `for lt in line_tokens`;
returning one line needs no builder change beyond the separator that previously sat
between the two lines (there was none — both lines were consecutive `content`
rows), so the row simply shrinks. Alternative (return a bare `str`) was rejected: it
breaks the builder's uniform `line_tokens` iteration and the existing tests' shape.

**D2 — Column widths from the merged strings, not fixed `IN_W/CACHE_W/OUT_W`.**
The merged `session/day` fields are variable-width, so the right-justify columns
(`IN_W=6` etc.) no longer make sense for the merged form. Compute the tokens and
cost column strings directly and measure with `_visible_width`. The session-only
variant keeps the original per-field justification. Rationale: slash-merged fields
have no natural fixed width; padding them to one looks ragged.

**D3 — New `GradientEngine.sparkline_1row(history, live)` method.** Add a pure
single-row sparkline: map each value to `round(ratio*8)` over `[0,8]`, index into
` ▁▂▃▄▅▆▇█`, colour by ratio via the existing `spark_color`, dim the last cell when
`live`. Remove the old two-row `sparkline` and the `_spark_rise/_spark_fall/
_spark_flat` helpers and their `SPARK_RISE_*`/`SPARK_FALL_*` constants once no
caller remains. Rationale: block elements (U+2581–U+2588) have near-universal font
coverage; the legacy half-block glyphs do not. A single row is sufficient at the
8-level resolution the rate display needs. Alternative (keep both, switch by config)
was rejected as needless surface area — the legacy path has no advocate.

**D4 — 60s window at the call site; drop the tick marker.** Change the history
fetch from `TokenRate.WINDOW * 2` to `TokenRate.WINDOW`. The 60s tick marker
(`spark_mark_col`) marked the 120s bar's midpoint; now that the whole bar is 60s it
marks nothing meaningful, so **remove it**. `tokens_cost` returns `mark_col = 0`
(or the triple drops to `(lines, vsep_cols)` if the builder is updated to match),
and `build_wide` no longer threads a spark-mark elbow. Rationale: the doubled
window predates the single-row design; 60s matches the resolved `token_window` and
the rate label's own averaging window, and a midpoint marker has no referent.

**D5 — `show_day_stats` as the seventh `Config` knob.** Add `show_day_stats: bool`
to `Config` (default `True`), resolved by the same precedence machinery: canonical
`YAS_SHOW_DAY_STATS`, `[tokens].show_day_stats`, boolean validation (env form:
`0`/`false`/`no` → false, any other non-empty → true; matching the existing
`full_width` boolean handling but with explicit false-y tokens). Thread it into
`tokens_cost` (via the builder, which already holds the `Config`/`SessionView`).
Rationale: reuses the entire config path; no new resolution code, only a new field
+ validator entry + default.

## Risks / Trade-offs

- **[Lost vertical separation of session vs day]** → The slash-merge keeps both
  numbers adjacent (`session/day`) with the session value first, and the cache pair
  in parentheses, so the reading order is preserved; the prototype confirmed it
  reads cleanly.
- **[Width pressure: merged line is wider per column]** → At ~100 cols the merged
  form is tight (the prototype overflowed two of three candidate shapes at 100).
  Mitigation: `show_day_stats=0` gives users on narrow terminals the session-only
  form; the wide layout only triggers above `MEDIUM_WIDTH=80` anyway. If needed, the
  builder can shed day stats automatically under a width threshold — deferred unless
  testing shows it necessary.
- **[Removing the legacy sparkline glyphs breaks callers/tests]** → Grep for
  `SPARK_RISE`/`SPARK_FALL`/`_spark_rise`/`_spark_fall`/`_spark_flat`/`.sparkline(`
  before deleting; update `test_gradient_math.py`. The two-row `sparkline` is only
  called from `tokens_cost`, so the blast radius is contained.
- **[Elbow drift]** → A single line changes which separator carries the tokens
  elbows. Verify via `make demo` across the width thresholds that every `┬`/`┴`
  still lines up, and assert divider columns in `test_layout_seam.py`.

## Migration Plan

Pure rendering + config change; no data migration. Rollout is the normal version
bump. Rollback is reverting the commit. `show_day_stats` defaults to the current
(day-stats-shown) behaviour, so existing users see only the height reduction and
the new sparkline unless they opt out. Delete `ops/proto_compact_tokens_row.py` and
its NOTES file as part of applying.

## Open Questions

_None — both resolved:_

- Cache parenthetical units: **keep `fmt_tok` suffixes** (`(1.2M/18.3M)`); bare
  numbers are ambiguous.
- 60s tick marker: **removed** (see D4) — a midpoint marker has no referent once the
  whole bar is 60s.
