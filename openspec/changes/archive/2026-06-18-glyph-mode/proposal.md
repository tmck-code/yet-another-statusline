## Why

The statusline currently has a single boolean `YAS_ASCII_MODE` that does one thing — replace every non-ASCII glyph with an ASCII equivalent. That is the right escape hatch for the most hostile terminals, but it is the *only* fallback. Users whose terminal has full Unicode support but no Nerd Font get either tofu boxes (`nerdfont`) or a needlessly degraded all-ASCII render (`ascii`); users whose font renders some glyphs double-width get a misaligned box with no remedy short of going full ASCII. A single enum knob with graded fallbacks lets each terminal pick the richest representation it can actually display.

## What Changes

- **BREAKING**: Replace the boolean `YAS_ASCII_MODE` env var / `[appearance].ascii_mode` toml key / `Config.ascii_mode` field with an enum `YAS_GLYPH_MODE` / `[appearance.glyphs].mode` / `Config.glyph_mode`. `YAS_ASCII_MODE=1` is superseded by `YAS_GLYPH_MODE=ascii`; the old name is removed (no legacy alias — the feature shipped recently and has no external consumers).
- Add three glyph modes, resolved through the existing config precedence chain (CLI → env → toml → default):
  - **`nerdfont`** (default): display all characters as-is. No translation. Full fidelity; requires a Nerd Font.
  - **`ascii`**: translate every non-ASCII glyph to a width-1 ASCII equivalent. The current `ascii_mode` behavior. Maximum compatibility.
  - **`unicode`**: translate **only** Nerd Font PUA icons to width-1 non-PUA Unicode equivalents, leaving box-drawing, block/sparkline, arrow, and punctuation glyphs intact. For terminals with good Unicode coverage but no Nerd Font.
- Add an **orthogonal** `single_width` boolean knob (`YAS_GLYPH_SINGLE_WIDTH` / `[appearance.glyphs].single_width` / `Config.single_width`, default `false`), resolved through the same precedence chain. When enabled it folds every double-width character (wide emoji, CJK) in the rendered output to a width-1 equivalent, so column math holds under fonts that render some glyphs double-width. It targets dynamic content (branch names, paths); the statusline's own glyphs are already width-1. Because it is a separate knob, it combines with **any** mode — e.g. `mode = unicode` + `single_width = true`.
- Both knobs reuse the single final-pass seam in `app.render`: the mode transform is applied first (picking which translation map applies; `nerdfont` is the identity, no pass), then the `single_width` fold when enabled. `nerdfont` + `single_width = false` is a full no-op.
- New `--glyph-mode <mode>` and `--glyph-single-width <bool>` CLI flags replace `--ascii-mode`.

## Capabilities

### New Capabilities
- `glyph-mode`: the glyph-rendering contract — what each of the three modes `nerdfont` / `ascii` / `unicode` does to the rendered output, the orthogonal `single_width` fold that composes with any mode, the width-preservation invariant every mode and the fold must hold, and the single-seam application model (mode transform first, then the fold).

### Modified Capabilities
- `statusline-config`: the config-knob set gains `glyph_mode` (enum `nerdfont|ascii|unicode`, default `nerdfont`) resolved via CLI `--glyph-mode` → `YAS_GLYPH_MODE` → `[appearance.glyphs].mode` → default, and `single_width` (boolean, default `false`) resolved via CLI `--glyph-single-width` → `YAS_GLYPH_SINGLE_WIDTH` → `[appearance.glyphs].single_width` → default. Both fall back to their default on an invalid value like every other knob. The transient `ascii_mode` boolean is removed.

## Impact

- **Code**: `claude/yas/config.py` (`glyph_mode` + `single_width` fields, parsers, resolution from the `[appearance.glyphs]` subtable, argv for both flags), `claude/yas/constants.py` (per-mode translation tables: keep `ASCII_TRANSLATE`, add a PUA→Unicode map; the singlewidth fold lives in `text.py`), `claude/yas/render/text.py` (`apply_glyph_mode` for the mode pass, `to_singlewidth` for the fold, and an `apply_glyphs` combiner that runs the mode then the optional fold), `claude/yas/app.py` (apply mode then fold at the render seam; `render()`/`main()` thread `glyph_mode` + `single_width`), `claude/mon.py` (honors both knobs via the same fallback — no change needed).
- **Tests**: `test/test_ascii_render.py` extended/renamed to cover the three modes, the `single_width` fold, their combinations, and the width-preservation invariant; `test/test_config.py` for the enum + boolean resolution.
- **Docs**: `CONTEXT.md` glyph-mode wording.
- **Migration**: anyone setting `YAS_ASCII_MODE=1` must switch to `YAS_GLYPH_MODE=ascii`.
