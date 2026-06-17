## 1. Pre-flight (skill checklist)

- [x] 1.1 Read `CONTEXT.md`; baseline `make test` (note pass count) and `make demo` (eyeball wide elapsed cell)
- [x] 1.2 Run the PUA-glyph scan over any lines to be edited in `renderer.py` / `constants.py`

## 2. Constants

- [x] 2.1 Add the clear-timer Nerd Font glyph constant to `constants.py` as an escaped literal (e.g. `GLYPH_CLEAR = '\\U000f0450'  # nf-md-refresh`), in the existing PUA block
- [x] 2.2 Add a head-scan line-budget constant (e.g. `CLEAR_SCAN_MAX_LINES = 30`)

## 3. Clear-marker reader (data source)

- [x] 3.1 Add `info/clear.py` with a bounded head-scan that returns the most-recent `/clear` epoch or `None` (pre-filter `'/clear' in ln and 'command-name' in ln`, cap at `CLEAR_SCAN_MAX_LINES`, reuse the `Z`→`+00:00` / `fromisoformat` timestamp idiom; swallow OSError/JSON/parse errors → `None`)
- [x] 3.2 Add `clear_epoch: float | None` as a `@cached_property` on `SessionView` in `info/__init__.py`

## 4. Renderer — two-timer composition

- [x] 4.1 Extend `elapsed_section` to accept an optional clear-timer string and compose clear-first (glyph + accent colour) followed by the grey 8-col session timer; return `(text, visible_width)`
- [x] 4.2 Pick the accent colour from the existing non-grey palette; keep the session-timer field at 8 right-justified columns

## 5. Layout — degradation ladder

- [x] 5.1 In `build_wide`, format the clear timer from `view.clear_epoch` and `view.now` (`_fmt_elapsed_clock(max(0, now − clear_epoch) * 1000)`)
- [x] 5.2 Compute both-timers and clear-only content widths; apply the existing `>= 5` path-protection test to both-width, then clear-only width, else shed (`elapsed_section_w = 0`)
- [x] 5.3 Verify the chosen content threads through the unchanged `elapsed_div_col` / vsep / elbow path (no new divider); fresh session (no `clear_epoch`) takes the original single-timer path unchanged

## 6. Tests

- [x] 6.1 `test_info.py`: reader returns epoch for a cleared transcript, `None` for fresh, bounded (no full scan past the cap), and `None` on malformed/missing input; `SessionView.clear_epoch` wiring
- [x] 6.2 elapsed-section test: composes one vs two timers, clear-first order, glyph/accent present only when cleared, `MM:SS` / `H:MM:SS` formatting, clock-skew clamp
- [x] 6.3 `test_layout_seam.py`: degradation ladder (both → clear-only → shed) and fresh-session byte-identical single-timer via an injected `SessionView`

## 7. Verification & docs

- [x] 7.1 `make test` green (baseline + new tests); `make demo` — elbows aligned, cell degrades correctly across widths, fresh session unchanged
- [x] 7.2 Update `CONTEXT.md` glossary if a new displayed term/glyph meaning is introduced
