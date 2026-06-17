## Context

The wide statusline is a single-pass terminal painter with hand-tuned column math. Its top border and separator rows are drawn in `claude/yas/render/borders.py` (`BorderRenderer.border_top`, `border_separator`, `border_separator_dim`) as an ordered list of `grad_at(pos) + char` parts joined into one string; the rainbow gradient is strictly positional (`t = col / (width - 1)`), so any out-of-order insertion decoheres colour from column. Section geometry (divider columns, section widths) is computed in `build_wide` (`claude/yas/layout.py`) and threaded to the border methods as `ups`/`downs` elbow columns via `RowSpec`. Config knobs resolve through a fixed precedence chain in `claude/yas/config.py` onto a frozen `Config`; `layout.justify` is the closest existing analog (wide-only, boolean, `view.cfg.justify`).

This change adds an opt-in `layout.labels` mode that overlays superscript section labels onto those existing border/separator rows, without adding any content rows.

## Goals / Non-Goals

**Goals:**
- A `layout.labels` boolean knob plumbed exactly like `layout.justify`.
- Superscript labels painted into the wide top border and separators, anchored above the values they name.
- Labels colourise positionally with the border gradient (and inherit the separator dim ramp) — no flat colour.
- Labels yield to elbows, frame corners, the session id, and the model pill; they truncate or drop rather than shift anything.
- Zero behaviour change when the flag is off, and in narrow/medium at any flag value.

**Non-Goals:**
- Labels in narrow/medium layouts.
- Per-helper column export from `renderer.py` (rejected below; anchoring instead measures the content strings `build_wide` already holds).
- Configurable label text or per-label toggles.
- Any change to the stdin payload, token/cost math, or on-disk formats.

## Decisions

### Decision: Per-column buffer overlay, then a single gradient pass

Refactor the three border methods to first build a per-column `chars: list[str]` buffer (length `width`) holding the base glyph for every column — frame corners, fill (`─`/`┄`), elbows (`┬`/`┴`/`┼`), and the embedded session id — exactly as today, then **overlay** label glyphs onto fill-only columns, then run a single ordered pass emitting `grad_at(col) + chars[col]`. Because the gradient pass still walks columns in order, colour stays coherent and labels colourise for free, including the dim factor on `border_separator_dim`.

*Why over splicing into the existing parts list:* the research showed inserting label parts mid-loop decoheres `grad_at(pos)` from the visual column. A column-indexed buffer makes overwrite-in-place trivial and keeps the gradient positional by construction.

*Alternative considered — paint labels as a post-process on the finished ANSI string:* rejected; re-parsing ANSI to find fill columns is fragile and re-derives width math the buffer already has.

### Decision: Labels yield to structural glyphs via a fill-only mask

Before overlay, mark which buffer columns are fill (the only overwritable kind). A label writes left-to-right from its anchor only across contiguous fill columns; it stops (truncates) at the first non-fill column (elbow, session id, pill, corner) and is dropped if its anchor is not fill. This guarantees no elbow/pill/session-id/column ever shifts — the spec's core invariant.

### Decision: `RowSpec.labels` carries `(text, start_col)` tuples; `build_wide` owns positions

Add `labels: list[tuple[str, int]] = field(default_factory=list)` to `RowSpec`. `build_wide` computes each label's 1-indexed start column by measuring the row's already-rendered content string — stripping ANSI and finding the whitespace-delimited token offset of the value the label names — guarded by `view.cfg.labels`. The divider/section-width variables it holds (`path_div_col`, `helper_anchor`, `sep_rate_col`, `cache_div_col`, the tokens/cost vsep columns) bound each measurement to the correct cell. `render_layout` passes `labels=row.labels` into `border_top`/`border_separator`/`border_separator_dim`. The superscript mapping is applied inside the border method (it stores ASCII; the method maps at paint time) so width math and the buffer stay in raw columns.

*Why measured content-column anchoring over both a tuned position table and per-value column export (refinement of the earlier decision):* the earlier draft chose a hand-tuned offset table over exact anchoring because exact anchoring seemed to require every section helper in `renderer.py` to export value→column maps — a large, fragile surface. The refined approach gets exactness without that export: `build_wide` already holds each row's rendered content string, so it strips ANSI and locates each value by its whitespace-delimited token offset, anchoring labels (including the per-sub-value 5h/7d labels) over the real columns. This stays contained to `layout.py` + the border primitive — no per-helper column export — and tracks the values precisely even as content shifts, retiring the tuned offset table.

### Decision: Superscript mapping lives in `render/text.py`

Add `superscript(s: str) -> str` next to the other width/format primitives. It maps letters/digits/`+`/`/`/space to their Unicode superscript glyphs via a module-level table, passing unmapped characters through unchanged so the output width always equals the input length. The glyphs are non-PUA (e.g. `ᵗ` U+1D57, `⁵` U+2075) and width-1 per `_visible_width`, so they need no PUA-constant hoisting.

## Risks / Trade-offs

- **Crooked box from an off-by-one in label columns** → labels never touch elbow columns (fill-only mask), so a wrong column can misplace a *label* but cannot move an elbow or break the frame; the demo visual check and border tests catch misplacement.
- **Gradient decoherence if the buffer pass regresses** → the single ordered `grad_at(col)` pass is the one invariant to preserve; a border test asserts a labelled row and its label-free counterpart are byte-identical except at the overlaid columns.
- **Tuned offsets drift as section content changes** → labels degrade gracefully (truncate/drop) and are cosmetic; they never affect content layout, so drift is a visual nicety, not a correctness bug.
- **A superscript glyph missing from a font** → unmapped/again-unsupported characters pass through as their ASCII form; worst case a label shows plain letters, still readable.
- **Label collides with the session id or pill** → fill-only mask drops/truncates it; covered by spec scenarios and tests.

## Migration Plan

Additive and off by default; no migration. Rollback is setting `labels = false` (the default) or reverting the change. No data or config format changes.
