## Why

The wide statusline packs many sections and sub-values (path/git changes, clear/session timers, 5h and 7d limit stats, cache countdown, token/cost columns, skills) into a dense box, but nothing names them — a new user has to memorise what each number means. An opt-in `layout.labels` mode paints small superscript labels into the border and separator lines directly above each value, turning the frame's empty fill into a legend without consuming any content rows.

## What Changes

- Add a new `layout.labels` boolean knob (default `false`), resolved through the existing precedence chain (`YAS_LABELS` env var → `[layout].labels` in `yas.toml` → default), mirroring `layout.justify`.
- When enabled (wide layout only, matching `justify`), paint superscript section labels into the rainbow top border and the dotted/solid separators above each section, anchored above the value they name (e.g. `clear`/`session` over the two elapsed timers, `5h`/`remain`/`used`/`burn rate` over the 5h stats).
- Labels colourise positionally with the border gradient — each glyph picks up the rainbow colour of the column it occupies — and yield to elbows (`┬┴┼`), the session id, and the model pill (never overwrite them; truncate/drop a label that would not fit).
- Add a superscript text primitive that maps ASCII label text to Unicode superscript glyphs, with graceful fallback for characters that have no superscript form.
- Document `layout.labels` in `yas.example.toml`.
- Narrow and medium layouts ignore the flag (no behaviour change).

## Capabilities

### New Capabilities
- `section-labels`: How the wide layout, when `cfg.labels` is enabled, overlays gradient-coloured superscript labels onto the top border and separator rows above each section/sub-value, and how those labels yield to elbows, session id, and the pill.

### Modified Capabilities
- `statusline-config`: Adds the `labels` knob (canonical `YAS_LABELS`, `[layout].labels`, default `false`) to the layered configuration set.

## Impact

- `claude/yas/constants.py`: new `DEFAULT_LABELS = False`.
- `claude/yas/config.py`: new `labels: bool` field on the `Config` dataclass plus its resolution.
- `claude/yas/render/text.py`: new superscript mapping primitive.
- `claude/yas/render/borders.py`: `border_top` / `border_separator` / `border_separator_dim` gain a `labels` parameter and overlay labels onto a per-column character buffer before the positional gradient pass.
- `claude/yas/layout.py`: `RowSpec` gains a `labels` field; `build_wide` computes label columns from its existing divider/width variables; `render_layout` threads `labels` into the border methods.
- Tests under `test/` (new `test_labels.py`, plus border/layout test updates).
- Docs: `yas.example.toml` and `CONTEXT.md` glossary.
- No change to narrow/medium layouts, the stdin payload, or on-disk formats.
