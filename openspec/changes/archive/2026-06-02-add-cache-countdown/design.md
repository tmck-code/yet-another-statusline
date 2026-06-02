## Context

The renderer is a layered, single-pass terminal painter. Derived session state is gathered once per render by `SessionView` (lazy `@cached_property` fields, one frozen `now`), and the wide layout is assembled by `build_wide` from `RowSpec`s with hand-tuned elbow/divider column math. Token usage already comes from `TranscriptUsage.from_transcript`, a single forward scan of the transcript jsonl that filters `"usage"` + `"assistant"` lines and sums token counts — but it currently ignores each line's `timestamp`.

The reference implementation is a PowerShell statusline (rodboev gist) that scans the transcript backward for the last cache-bearing line, anchors a TTL countdown on its timestamp, persists the epoch to a per-session state file, and prints `cache <m:ss>` coloured green→red by percent-of-TTL-elapsed.

This design ports that behaviour onto the existing primitives, wide layout only.

## Goals / Non-Goals

**Goals:**
- Show time remaining until the prompt cache expires, as a vsep-delimited section on the wide path/model row.
- Reuse the single transcript scan, the frozen `now`, the `fill_colour` ladder, and `fmt_dur` — minimal new surface.
- Keep `SessionView` pure (raw data, no ANSI/geometry); keep all width/elbow math in `build_wide`/renderer.
- Hide cleanly (section + divider) on expiry, no-event, and width pressure.

**Non-Goals:**
- Medium/narrow rendering (unchanged).
- A persisted cache-state file (we re-derive every render).
- Tracking cache state for sessions other than the one being rendered (the multi-session observer is out of scope here).
- Changing how `Cache Read` token counts are displayed in the tokens row.

## Decisions

**Anchor = transcript timestamp of the last cache-bearing line.** Alternatives: (a) transcript file mtime — cheapest, but moves on any write, not just cache events, so it drifts; (b) the `TokenRate` activity log's newest epoch — already epoch-stamped, but keyed on token-delta growth, not cache events. Chosen the transcript timestamp because it is the actual cache-write wall-clock time; the other two are proxies that misfire. A cache *read* (`cache_read_input_tokens > 0`) counts as activity because reading the cache refreshes its TTL, so every cached turn re-anchors the countdown.

**TTL tier detected per anchor line.** `3600` s when `cache_creation.ephemeral_1h_input_tokens > 0`, else `300` s. Alternative: hardcode 300 s (simplest) or a config knob. Chosen per-line detection to match real behaviour for 1h-ephemeral users without configuration; the TTL becomes part of the raw anchor data, not a constant.

**Hybrid reader/derivation split.** Raw anchor (`cache_anchor_epoch`, `cache_ttl`) lives on `TranscriptUsage`, populated in the existing single scan (retain the most-recent cache line's raw timestamp string, parse once after the loop via the `session` ISO helper). The `now`-relative math (`remaining`, `elapsed_pct`) lives on `SessionView.cache_countdown`. Rationale: the file-touching half can only be produced during the scan and cannot be peeled into a standalone property without a second read (which would break the "scan once" invariant); the time math depends on `now`, which `TranscriptUsage` neither has nor should have. So the split is raw-extraction vs now-relative-derivation, not reader-vs-reader.

**No persisted state file.** The gist writes `.sl_cache_<session>` to survive render ticks. We re-derive the anchor from the transcript every render and compute against the fresh frozen `now`, exactly as `elapsed` and the Task Timers already do — so the state file is unnecessary. One fewer disk artifact and no stale-state class of bug.

**Placement: own vsep section on the path/model row, one left divider, before the model section.** Lands in the existing `pad` gap between the rate-limit helper (`helper_text`) and the flush-right model section/pill (`right_text`). Alternatives: append to the tokens-row cluster (adjacent to `Cache Read`), a standalone row, the model-row helper suffix like the rate limits, or the context row. Chosen the path/model row per the design owner; it co-locates the cache time with the other live per-turn stats and avoids spending a whole vertical line.

**Colour via `fill_colour(elapsed_pct)`.** Reuses the theme safe/warn/alert ladder (same as the rate-limit percentages and Compaction-Risk Zone) rather than introducing the gist's parallel 4-stop ramp or a continuous gradient. `elapsed_pct = 100 − round(remaining·100/ttl)` rises as the cache ages, and `fill_colour` reds-out at high pct, so fresh = green, near-expiry = red.

**Format via `fmt_dur`.** Already emits `42s` / `3m07s` / `1h05m` — the exact gist format — so no new formatter.

**Glyph `GLYPH_CACHE = ''` (nf-oct-cache).** Hoisted to `constants.py` as a named escape per the PUA rule (literal PUA bytes get dropped through edit/chat round-trips).

**Data shape: view returns `(remaining, elapsed_pct)` or `None`; `build_wide` owns width-shed.** `None` covers the two gist hide cases (no anchor, expired). The third hide case (width pressure) is a render concern that needs the section's visible width, so it lives in `build_wide`, which sheds the Cache Countdown first (before truncating the path).

## Risks / Trade-offs

- **Elbow threading next to the flush-right pill** → This is the trickiest column math in the renderer (pill border-math + a new adjacent divider). Mitigation: thread exactly one new elbow column into `top_border.downs` / `separator_dim.ups`, subtract the section's visible width from `target_w`/`pad`, and verify with `make demo` across wide widths both with and without the thinking pill.
- **Divider must drop-and-rethread on three independent hide conditions** → A stale elbow with no `│` beneath draws a crooked box. Mitigation: compute section presence once in `build_wide`, derive the row's `downs`/`ups` from that single boolean, and add a test asserting only the path elbow remains when hidden.
- **Width-shed threshold is fuzzy** → Too eager hides a fitting countdown; too lax shoves the pill. Mitigation: derive the threshold from the section's own visible width plus a 1-column minimum gap to the model section; cover with a width-boundary test.
- **`elapsed_pct` rounding at the edges** → `round()` can yield `0` or `100` at the boundaries; ensure colour-band lookups are clamped to `[0, 100]`.
- **Timestamp parse failures** → Malformed or missing `timestamp` on the anchor line. Mitigation: treat parse failure as "no anchor" (`cache_anchor_epoch = 0.0` → `cache_countdown = None`), never raise into the render.

## Migration Plan

Additive and wide-only; medium/narrow and all token-accounting outputs are byte-for-byte unchanged. No data migration, no new dependency, no config. Rollback is reverting the change — there is no persisted state to clean up.

## Open Questions

- Exact width-shed threshold (column count) — to be pinned during implementation from the section's measured width plus a 1-column gap; not expected to need design-level resolution.
