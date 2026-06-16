## 1. Constants

- [x] 1.1 Add `ICON_LIMIT_5H = '\U000f051b'` (nf-md-timer_outline 󰔛) to `constants.py` alongside the existing glyph block, encoded as an escape.
- [x] 1.2 Add `ICON_LIMIT_7D = '\U000f0a34'` (nf-md-calendar_week_begin 󰨴).
- [x] 1.3 Add `GLYPH_MODEL_LIGHT = '\U000f1a51'` (nf-md-lightbulb_on_40 󱩑).
- [x] 1.4 Add `SEP_RATE = '┆'` (dotted vertical ┆).

## 2. Session timer

- [x] 2.1 In `info/__init__.py`, change `_fmt_elapsed_clock` to drop the hours field when hours == 0 (return `MM:SS`), keeping `H:MM:SS`/`HH:MM:SS` when hours > 0; preserve the empty-string return for ms <= 0.
- [x] 2.2 In `renderer.py` `elapsed_section`, right-justify the timer string into a fixed 8-column field (`HH:MM:SS` worst case) and return the padded width via `_visible_width`.

## 3. Rate-limit segments

- [x] 3.1 In `renderer.py` `helper` (5-hour), lead the segment with `ICON_LIMIT_5H` (replacing the prior helper glyph) and move the reset countdown to the front as `(-H:MM)` (parens, leading minus, hours kept, seconds dropped, single-digit hour); keep the existing infinite-indicator path with no countdown.
- [x] 3.2 Format the 5-hour usage percentage to one decimal place (`{float(pct):.1f}`).
- [x] 3.3 In `renderer.py` `model_right_section`, lead the 7-day segment with `ICON_LIMIT_7D`, format its usage percentage to one decimal place, and change the 5h/7d separator from ` | ` to ` ┆ ` (`SEP_RATE`).
- [x] 3.4 In `renderer.py` `burndown_trend`, change the delta format from `{:05.2f}` to `{:.1f}` (covers both 5h and 7d trends).

## 4. Cache countdown

- [x] 4.1 In `renderer.py` `cache_section`, replace `fmt_dur(remaining)` with `MM:SS` (zero-padded), rolling to `H:MM:SS` at or above 3600 s; keep `GLYPH_CACHE` and the `fill_colour(elapsed_pct)` colour.

## 5. Model pill

- [x] 5.1 In `renderer.py` `model_right_section`, collapse to a single lead glyph `GLYPH_MODEL_LIGHT` (drop both monitor and brain), add one space of left padding after the pill edge, and keep the fast-mode swap to `GLYPH_BURN_FAST` on the lead glyph.
- [x] 5.2 Render the effort/thinking value as parenthesised text `(value)` after the model name; omit the parens entirely when the value is empty.
- [x] 5.3 In `model_section_compact` and `model_right_section_compact`, swap `GLYPH_MODEL` to `GLYPH_MODEL_LIGHT` and format the usage percentage to one decimal place.

## 6. Tests

- [x] 6.1 Update/add `test/test_model_section.py` for the single lightbulb glyph, leading padding, parenthesised effort, empty-effort omission, fast-mode swap, and compact glyph.
- [x] 6.2 Update/add rate-limit tests for the 5h/7d icons, `(-H:MM)` countdown placement, ` ┆ ` separator, and one-decimal usage/trend percentages.
- [x] 6.3 Update/add `test/test_info.py` (or equivalent) for `_fmt_elapsed_clock` MM:SS vs H:MM:SS, and a renderer test for the 8-column timer reservation.
- [x] 6.4 Update the cache-countdown rendering test(s) for the `MM:SS` / `H:MM:SS` format (e.g. `(187, 38)` → `03:07`, 3905 s → `1:05:05`).

## 7. Verification & docs

- [x] 7.1 Run `make test` — green, pass count >= baseline plus added tests.
- [x] 7.2 Run `make demo` — eyeball narrow/medium/wide; confirm every `┬` aligns with a `│` and a `┴`, pill colours flow, and the timer column is stable.
- [x] 7.3 Update `CONTEXT.md` glossary for any changed displayed term (cache time format, rate-limit icons, model glyph, timer format).
