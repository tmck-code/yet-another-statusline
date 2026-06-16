## Context

The wide top row is painted by section helpers on `Renderer` (`elapsed_section`, `helper`, `cache_section`, `model_right_section`, `burndown_trend`) plus the two compact model helpers, with the session-timer string formatted upstream by `_fmt_elapsed_clock` in `info/__init__.py`. Column geometry is recomputed by `build_wide` from each section's visible width, so changes that alter a section's width re-thread the box elbows automatically — provided the helpers return accurate `_visible_width` and `div_offset` values. All glyphs are Nerd Font PUA and live as named escapes in `constants.py`.

This change is presentation-only. No data source, gather seam, or token accounting changes. Several of the requested tweaks are inferred from the user's mockup rather than the bullet list, and were confirmed in a grilling session before this proposal (icon→limit mapping, reset-countdown reposition, dotted separator, fixed-width timer).

## Goals / Non-Goals

**Goals:**
- A single, legible time/percentage vocabulary across the top row.
- Stable column geometry — the timer column must not shift when the clock gains an hours digit.
- Cross-width consistency for the model glyph.
- Keep box-elbow alignment correct at every width threshold (validated by `make demo`).

**Non-Goals:**
- No change to the data layer (`SessionView`, `TranscriptUsage`, `cache_countdown` derivation, token accounting).
- No change to medium/narrow layout *structure* — only the shared model glyph and percentage precision propagate there.
- No new rows, sections, or dividers; the set of top-row dividers (path, timer, cache) is unchanged.

## Decisions

- **Icon→limit mapping follows the mockup, not the bullet labels.** The user's written labels assigned timer-outline to 7-day and calendar-week to 5-hour, which is both semantically backwards and contradicts the mockup. Resolved: 5-hour → `ICON_LIMIT_5H` (timer-outline 󰔛, U+F051B), 7-day → `ICON_LIMIT_7D` (calendar-week 󰨴, U+F0A34). These replace the previous `GLYPH_HELPER` lead on the rate segment.

- **Model glyph is a third, new glyph.** Neither monitor (`GLYPH_MODEL`) nor brain (`GLYPH_THINKING`) survives; the single lead becomes `GLYPH_MODEL_LIGHT` (lightbulb-on 󱩑, U+F1A51), applied in the wide pill and both compact pills. Fast mode continues to swap the lead to `GLYPH_BURN_FAST`. Rationale: the user explicitly chose this glyph during grilling; one icon de-clutters the pill.

- **Effort/thinking is parenthesised text, not a glyph.** The pill renders `… <model> (medium)`; when the effort/thinking value is empty, the parens are omitted entirely (no empty `()`).

- **Timer reserves a fixed 8-char field.** `_fmt_elapsed_clock` drops the leading `0:` under an hour (`MM:SS`), keeping `H:MM:SS`/`HH:MM:SS` otherwise; `elapsed_section` right-justifies the result into 8 columns (`HH:MM:SS` worst case). Chosen over natural width so the box column is stable across the whole session; chosen over a 7-char reserve so 10h+ sessions don't overflow by a column.

- **Two distinct time reformats, deliberately different.** The 5-hour *reset countdown* becomes `(-H:MM)` (hours kept, seconds dropped) because it spans hours; the *cache countdown* becomes `MM:SS` rolling to `H:MM:SS` because it is normally seconds-to-minutes. They are not unified.

- **Percentage precision centralised where possible.** `burndown_trend` moves from `{:05.2f}` to `{:.1f}`, covering both 5h and 7d trends in one edit. Usage percentages are wrapped at each render site (`helper`, the 7-day branch, and both compact helpers) as `{float(pct):.1f}`.

- **Width re-threading is automatic.** Because `build_wide` derives divider columns from section widths, no manual elbow column edits are needed; correctness is confirmed visually rather than by hand-computed offsets.

## Risks / Trade-offs

- **Crooked box from a stale width** → Every helper that changed its content must return a matching `_visible_width`; verify with `make demo` across narrow/medium/wide, watching `┬`/`│`/`┴` alignment.
- **PUA glyphs lost through edits** → All four glyphs are added to `constants.py` as `\u`/`\U` escapes first, then imported by name; no raw glyph is typed into renderer edits (per the skill's PUA rule).
- **`MM:SS` overflow if a cache TTL exceeds an hour** → Handled by rolling to `H:MM:SS` at/over 60 min rather than printing minutes ≥ 60.
- **Fixed 8-char timer wastes ~3 columns for short sessions** → Accepted; geometry stability is worth more than the columns, and the wide layout has the room.
- **Compact glyph swap touches narrow/medium output** → Intentional for consistency; covered by updating the corresponding tests.
