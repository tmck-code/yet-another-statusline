## Context

The wide layout's top content row is assembled in `build_wide` (`layout.py`) as a sequence of sections separated by vsep blocks (`  │  `). Currently all horizontal slack — `target_w - path_w` — flows into the path section as trailing space, leaving the other sections (elapsed, helper, cache) at their natural minimum widths and a large blank stretch before the right pill.

The sections present in a wide top row, in order, are:
1. **path** — always active; content left-aligned
2. **elapsed** — optional (only when elapsed or since-/clear timer exists); content centered
3. **helper** — always active (`helper_text` from `model_right_section`); content centered
4. **cache** — optional (only when a cache countdown exists); content centered
5. **last-slot** — always active; the space between the final section and the right pill/text

Each section is delimited on its right by a vsep block whose absolute column is tracked in `path_row_cols` for border elbow threading (`ups`/`downs` on `RowSpec`).

## Goals / Non-Goals

**Goals:**
- Distribute horizontal slack evenly across active top-row sections
- Keep path content left-aligned within its wider slot
- Center content in elapsed, helper, and cache slots
- Shift all vsep column references to match the new positions (elbow math stays correct)
- Gate the feature behind `cfg.justify` (default `false`)

**Non-Goals:**
- Justification in medium or narrow layouts
- Changing section content or rendering logic
- Centering the path content itself

## Decisions

### D1: Equal distribution, not proportional

Distribute `total_slack = target_w - path_w` as `extra_per = total_slack // N` per section, with the integer remainder spread one column at a time from left to right. Rationale: proportional distribution would give disproportionate space to the path (already the widest section), undermining the goal of visual balance. Equal distribution matches the mockup and is simpler.

### D2: N includes the last slot

The space between the end of the assembled `middle` string and the right pill is treated as a full slot. This ensures the pill appears well-separated from the last content section and gives the most uniform visual result. If the pill is active (`pill_pct` is set), the extra space is appended to `middle` before the right-pill painting path; in non-pill mode it adds to the existing `pad` calculation.

### D3: Fallback when total_slack == 0

When the path already fills `target_w`, there is no slack to distribute. `build_wide` falls through to normal layout silently. Sub-N slack (0 < total_slack < N) still distributes its remainder columns — a 1-column shift is still worth applying.

### D4: Div col arithmetic, not re-rendering

Rather than re-computing sections with different widths, the implementation inserts literal space strings around section content and offsets every tracked column by the cumulative padding of all preceding sections. This is purely arithmetic and requires no changes to section helpers.

The offsets accumulate as:
- `path_shift = path_extra` (trailing spaces after path, before vsep)
- `elapsed_shift = path_shift + elapsed_extra` (left + right centering padding)
- `helper_shift = elapsed_shift + helper_extra`
- `cache_shift = helper_shift + cache_extra`
- `sep_rate_col` (the `┆` inside `helper_text`) shifts by `elapsed_shift + h_left`

### D5: Config wiring follows existing `full_width` pattern

`DEFAULT_JUSTIFY = False` goes in `constants.py`. The `Config` dataclass gets a `justify: bool = DEFAULT_JUSTIFY` field. `Config.load` resolves it from `YAS_JUSTIFY` env and `[layout].justify` TOML key using the existing `_parse_bool` / `_env_sources` / `toml_src` pattern. No CLI flag is added (no existing precedent for boolean layout knobs as CLI flags).

## Risks / Trade-offs

- **Elbow misalignment if column arithmetic is off by one** → Risk is low because the existing `path_row_cols` accumulation pattern is well-tested; the new code follows the same pattern with explicit offset variables that are easy to inspect.
- **Subtle centering off-by-one for odd extra amounts** → Resolved by `left = extra // 2`, `right = extra - left`, which always sums to `extra`.
- **Feature is opt-in by default** → No risk to existing users.

## Open Questions

None — all design decisions were resolved during the proposal interview.
