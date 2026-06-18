## 1. Config: enum mode + orthogonal boolean

- [x] 1.1 In `claude/yas/config.py`, replace the `ascii_mode: bool = False` field with `glyph_mode: str = 'nerdfont'` on the frozen `Config` dataclass.
- [x] 1.2 Add a `single_width: bool = False` field to the `Config` dataclass.
- [x] 1.3 `_parse_glyph_mode(raw, origin)` accepts one of `nerdfont|ascii|unicode` (case-insensitive), raising `ValueError` otherwise (mirrors `_parse_bg_shift`); `single_width` reuses `_parse_bool`.
- [x] 1.4 In `_parse_argv`, keep `--glyph-mode <v>` / `--glyph-mode=<v>` and add `--glyph-single-width <v>` / `--glyph-single-width=<v>` → `out['single_width']`. (Replaced `--ascii-mode`.)
- [x] 1.5 Read both knobs from the `[appearance.glyphs]` subtable: fetch `glyphs` as a nested table off `appearance` (`{}` when absent/not-a-dict). Resolve `glyph_mode` from `cli_src('glyph_mode') + _env_sources(env, 'YAS_GLYPH_MODE') + toml_src(glyphs, 'mode')`; resolve `single_width` from `cli_src('single_width') + _env_sources(env, 'YAS_GLYPH_SINGLE_WIDTH') + toml_src(glyphs, 'single_width')` with `_parse_bool`, default `False`. Add `single_width=single_width` to the `cls(...)` return.

## 2. Translation tables and transforms

- [x] 2.1 In `claude/yas/constants.py`, keep `ASCII_GLYPHS`/`ASCII_TRANSLATE` unchanged. `UNICODE_PUA` maps each PUA glyph constant (21 `ICON_*`/`GLYPH_*` + `BarChars.MID`) to its width-1 non-PUA replacement; `UNICODE_TRANSLATE = {ord(g): u for g, u in UNICODE_PUA.items()}`.
- [x] 2.2 In `claude/yas/render/text.py`, `SINGLEWIDTH_PLACEHOLDER` (reuse `MIDDLE_DOT`) and `to_singlewidth(s)`: walk chars, keep non-`_is_wide`; for wide chars use an NFKC single-char narrow form if one exists, else the placeholder.
- [x] 2.3 In `claude/yas/render/text.py`, `apply_glyph_mode(s, mode)` dispatches only `nerdfont`→`s`, `ascii`→`s.translate(ASCII_TRANSLATE)`, `unicode`→`s.translate(UNICODE_TRANSLATE)` (no `singlewidth` branch). Add `apply_glyphs(s, mode, single_width)` = `apply_glyph_mode` then `to_singlewidth` iff `single_width`.

## 3. Wire the seam

- [x] 3.1 In `claude/yas/app.py`, `render(...)` takes `glyph_mode: str | None = None` and `single_width: bool | None = None`; each falls back to `cfg.glyph_mode` / `cfg.single_width` when `None`; the return is `apply_glyphs('\n'.join(render_layout(spec, r)), glyph_mode, single_width)`. Update the `yas.render.text` import.
- [x] 3.2 In `main()`, pass `glyph_mode=cfg.glyph_mode, single_width=cfg.single_width` to `render(...)`.
- [x] 3.3 Confirm `claude/mon.py` needs no change (kwarg-less `render` call inherits both knobs via the `is None` fallback).

## 4. Tests

- [x] 4.1 Rework `test/test_ascii_render.py` into a glyph suite: parametrize the three modes × `single_width ∈ {false, true}` and assert per-line `_visible_width` equals the `nerdfont`/no-fold render at widths 50/70/160.
- [x] 4.2 `ascii` → zero codepoints ≥ U+0080; `unicode` → zero PUA codepoints (both ranges) AND a representative box/block/arrow glyph still present; fold (`single_width=true`) → inject a double-width char into dynamic content and assert no `_is_wide` char remains and width is preserved, for `nerdfont`+fold and `unicode`+fold; `nerdfont`+no-fold → byte-identical to untransformed render.
- [x] 4.3 Coverage guard: every PUA glyph constant has an entry in BOTH `ASCII_GLYPHS` and `UNICODE_PUA`; every `UNICODE_PUA` value is a single non-PUA char.
- [x] 4.4 In `test/test_config.py`, add resolution tests: `glyph_mode` env/toml-subtable/cli select a mode, default `nerdfont`, invalid falls back + recorded; `single_width` env (`YAS_GLYPH_SINGLE_WIDTH`)/toml-subtable/cli resolve the bool, default `false`; the two knobs combine independently.

## 5. Docs and verification

- [x] 5.1 Update `CONTEXT.md`, `README.md`, and `yas.example.toml` to describe the three modes, the orthogonal `single_width` knob, the `[appearance.glyphs]` subtable, and the `YAS_GLYPH_MODE`/`YAS_GLYPH_SINGLE_WIDTH` env vars + `--glyph-mode`/`--glyph-single-width` CLI flags (and the removal of `YAS_ASCII_MODE`).
- [x] 5.2 Run `make test`; all green. Manually verify combinations via `YAS_GLYPH_MODE=<mode> YAS_GLYPH_SINGLE_WIDTH=<0|1> COLUMNS=160 python3 claude/statusline_command.py < ops/session-info-example.json`.
- [x] 5.3 Visual check: `make demo/img` + `yas-demo-text` diff against the `nerdfont`/no-fold baseline to confirm no column drift (default render must be byte-identical).
