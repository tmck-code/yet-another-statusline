## Why

The statusline currently has a single boolean `YAS_ASCII_MODE` that does one thing — replace every non-ASCII glyph with an ASCII equivalent. That is the right escape hatch for the most hostile terminals, but it is the *only* fallback. Users whose terminal has full Unicode support but no Nerd Font get either tofu boxes (`nerdfont`) or a needlessly degraded all-ASCII render (`ascii`); users whose font renders some glyphs double-width get a misaligned box with no remedy short of going full ASCII. A single enum knob with graded fallbacks lets each terminal pick the richest representation it can actually display.

## What Changes

- **BREAKING**: Replace the boolean `YAS_ASCII_MODE` env var / `[appearance].ascii_mode` toml key / `Config.ascii_mode` field with an enum `YAS_GLYPH_MODE` / `[appearance].glyph_mode` / `Config.glyph_mode`. `YAS_ASCII_MODE=1` is superseded by `YAS_GLYPH_MODE=ascii`; the old name is removed (no legacy alias — the feature shipped recently and has no external consumers).
- Add four glyph modes, resolved through the existing config precedence chain (CLI → env → toml → default):
  - **`nerdfont`** (default): display all characters as-is. No translation. Full fidelity; requires a Nerd Font.
  - **`ascii`**: translate every non-ASCII glyph to a width-1 ASCII equivalent. The current `ascii_mode` behavior. Maximum compatibility.
  - **`unicode`**: translate **only** Nerd Font PUA icons to width-1 non-PUA Unicode equivalents, leaving box-drawing, block/sparkline, arrow, and punctuation glyphs intact. For terminals with good Unicode coverage but no Nerd Font.
  - **`singlewidth`**: fold every double-width character (wide emoji, CJK) in the rendered output to a width-1 equivalent, so column math holds under fonts that render some glyphs double-width. Targets dynamic content (branch names, paths); the statusline's own glyphs are already width-1.
- All modes reuse the single final-pass translation seam in `app.render`; mode selection picks which translation map / pass applies. `nerdfont` is the identity (no pass).
- A new `--glyph-mode <mode>` CLI flag replaces `--ascii-mode`.

## Capabilities

### New Capabilities
- `glyph-mode`: the four-mode glyph-rendering contract — what each of `nerdfont` / `ascii` / `unicode` / `singlewidth` does to the rendered output, the width-preservation invariant every mode must hold, and the single-seam application model.

### Modified Capabilities
- `statusline-config`: the config-knob set gains `glyph_mode` (enum `nerdfont|ascii|unicode|singlewidth`, default `nerdfont`) resolved via CLI `--glyph-mode` → `YAS_GLYPH_MODE` → `[appearance].glyph_mode` → default, with invalid values falling back to the default like every other knob. The transient `ascii_mode` boolean is removed.

## Impact

- **Code**: `claude/yas/config.py` (field + parser + resolution + argv), `claude/yas/constants.py` (per-mode translation tables: keep `ASCII_TRANSLATE`, add a PUA→Unicode map and a singlewidth-folding helper), `claude/yas/render/text.py` (`to_ascii` generalized / new `apply_glyph_mode`), `claude/yas/app.py` (select pass by mode at the render seam; `main()` passes `glyph_mode`), `claude/mon.py` (honors the new knob via the same fallback).
- **Tests**: `test/test_ascii_render.py` extended/renamed to cover all four modes and the width-preservation invariant per mode; `test/test_config.py` for the enum resolution.
- **Docs**: `CONTEXT.md` glyph-mode wording.
- **Migration**: anyone setting `YAS_ASCII_MODE=1` must switch to `YAS_GLYPH_MODE=ascii`.
