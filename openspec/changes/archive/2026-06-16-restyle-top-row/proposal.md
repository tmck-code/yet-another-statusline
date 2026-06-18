## Why

The wide top row's session timer, rate-limit segments, cache countdown, and model pill have grown inconsistent: mixed time formats (`0:13:27`, `T-2:00:00`, `4m29s`), two-decimal trend percentages next to one-decimal usage percentages, two glyphs on the model pill, and a column that shifts as the session clock gains an hours digit. This change settles a single, legible presentation for the whole row.

## What Changes

- **Session timer**: drop the leading `0:` under an hour (`0:13:27` → `13:27`); right-justify into a fixed 8-char field (`HH:MM:SS`) so the column never shifts as the clock crosses `MM:SS` → `H:MM:SS` → `HH:MM:SS`.
- **5-hour segment**: lead with a timer-outline icon (󰔛); move the reset countdown to the front of the segment as `(-H:MM)` (seconds dropped, parens, single-digit hour), ahead of the usage and trend percentages.
- **7-day segment**: lead with a calendar-week icon (󰨴); change the divider between the 5-hour and 7-day segments from ` | ` to a dotted ` ┆ `.
- **Percentages**: render both usage and trend percentages at exactly one decimal place, in wide and compact layouts.
- **Cache countdown**: replace the `fmt_dur` format (`4m29s`) with `MM:SS`, rolling to `H:MM:SS` at or above an hour; keep the existing cache glyph.
- **Model pill**: collapse to a single leading glyph (lightbulb 󱩑), dropping both the monitor and brain glyphs; add one space of left padding after the pill edge; wrap the effort/thinking value in parentheses `(medium)`, omitted entirely when empty; fast mode still swaps the lead glyph to the burn glyph. Compact model pills swap to the same lightbulb glyph for cross-width consistency.

## Capabilities

### New Capabilities
- `top-row-format`: presentation rules for the wide top row — session-timer format and fixed-width reservation, rate-limit segment styling (5h/7d icons, reset-countdown placement and format, percentage precision, dotted inter-segment separator), and model-pill styling (single lightbulb glyph, left padding, parenthesised effort, fast-mode glyph swap) including compact-layout glyph consistency.

### Modified Capabilities
- `cache-countdown`: the wide-layout Cache Countdown rendering requirement changes its time format from `fmt_dur` (`42s`, `3m07s`, `1h05m`) to `MM:SS`, rolling to `H:MM:SS` at or above an hour. The cache glyph, positioning, colour, and elbow threading are unchanged.

## Impact

- `claude/yas/constants.py`: new glyph constants (`ICON_LIMIT_5H`, `ICON_LIMIT_7D`, `GLYPH_MODEL_LIGHT`, `SEP_RATE`).
- `claude/yas/info/__init__.py`: `_fmt_elapsed_clock` drops the leading `0:` under an hour.
- `claude/yas/renderer.py`: `elapsed_section` (fixed-width reservation), `cache_section` (MM:SS/H:MM:SS), `helper` (5h icon, countdown reposition/format, 1dp), `model_right_section` (7d icon, dotted separator, 1dp, single glyph, padding, parens), `burndown_trend` (1dp), `model_section_compact` / `model_right_section_compact` (lightbulb glyph, 1dp).
- Tests under `test/` and the term glossary in `CONTEXT.md`.
