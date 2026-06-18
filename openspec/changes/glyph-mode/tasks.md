## 1. Config: replace boolean with enum

- [ ] 1.1 In `claude/yas/config.py`, replace the `ascii_mode: bool = False` field with `glyph_mode: str = 'nerdfont'` on the frozen `Config` dataclass.
- [ ] 1.2 Add `_parse_glyph_mode(raw, origin)` that lower-cases and accepts one of `nerdfont|ascii|unicode|singlewidth`, raising `ValueError` otherwise (mirrors `_parse_bg_shift`).
- [ ] 1.3 Replace the `--ascii-mode` branches in `_parse_argv` with `--glyph-mode <v>` / `--glyph-mode=<v>`.
- [ ] 1.4 Replace the `ascii_mode` resolve block with a `glyph_mode` resolve: `cli_src('glyph_mode') + _env_sources(env, 'YAS_GLYPH_MODE') + toml_src(appearance, 'glyph_mode')`, parser `_parse_glyph_mode`, default `'nerdfont'`; remove the `YAS_ASCII_MODE` source and the `ascii_mode=` constructor arg, add `glyph_mode=glyph_mode`.

## 2. Translation tables and transforms

- [ ] 2.1 In `claude/yas/constants.py`, keep `ASCII_GLYPHS`/`ASCII_TRANSLATE` unchanged. Add `UNICODE_PUA` mapping each PUA glyph constant (21 `ICON_*`/`GLYPH_*` + `BarChars.MID`) to its width-1 non-PUA replacement per design.md, and `UNICODE_TRANSLATE = {ord(g): u for g, u in UNICODE_PUA.items()}`.
- [ ] 2.2 In `claude/yas/render/text.py`, add `SINGLEWIDTH_PLACEHOLDER` (reuse `MIDDLE_DOT`) and `to_singlewidth(s)`: walk chars, keep non-`_is_wide`; for wide chars use an NFKC single-char narrow form if one exists, else the placeholder. Import `unicodedata`.
- [ ] 2.3 In `claude/yas/render/text.py`, add `apply_glyph_mode(s, mode)` dispatching: `nerdfont`→`s`; `ascii`→`s.translate(ASCII_TRANSLATE)`; `unicode`→`s.translate(UNICODE_TRANSLATE)`; `singlewidth`→`to_singlewidth(s)`. (Generalize/retire the existing `to_ascii` or keep it as the `ascii` branch's implementation.)

## 3. Wire the seam

- [ ] 3.1 In `claude/yas/app.py`, change `render(...)`'s `ascii_mode: bool | None` param to `glyph_mode: str | None = None`; after `cfg = Config.load()` add `if glyph_mode is None: glyph_mode = cfg.glyph_mode`; change the return to `apply_glyph_mode('\n'.join(render_layout(spec, r)), glyph_mode)`. Update the import from `yas.render.text`.
- [ ] 3.2 In `main()`, pass `glyph_mode=cfg.glyph_mode` to `render(...)`.
- [ ] 3.3 Confirm `claude/mon.py` needs no change (kwarg-less `render` call inherits `cfg.glyph_mode` via the `is None` fallback).

## 4. Tests

- [ ] 4.1 Rework `test/test_ascii_render.py` into a glyph-mode suite: parametrize the four modes and assert per-line `_visible_width` equals the `nerdfont` render at widths 50/70/160.
- [ ] 4.2 `ascii` → zero codepoints ≥ U+0080; `unicode` → zero PUA codepoints (both ranges) AND a representative box/block/arrow glyph still present; `singlewidth` → inject a double-width char into dynamic content and assert no `_is_wide` char remains and width is preserved; `nerdfont` → byte-identical to untransformed render.
- [ ] 4.3 Coverage guard: every PUA glyph constant has an entry in BOTH `ASCII_GLYPHS` and `UNICODE_PUA`; every `UNICODE_PUA` value is a single non-PUA char.
- [ ] 4.4 In `test/test_config.py`, add `glyph_mode` resolution tests: env/toml/cli select a mode, default is `nerdfont`, invalid value falls back to `nerdfont` and is recorded.

## 5. Docs and verification

- [ ] 5.1 Update `CONTEXT.md` glyph-mode wording to describe the four modes and the removal of `YAS_ASCII_MODE` (migrate to `YAS_GLYPH_MODE=ascii`).
- [ ] 5.2 Run `make test`; all green. Manually verify each mode via `YAS_GLYPH_MODE=<mode> COLUMNS=160 python3 claude/statusline_command.py < ops/session-info-example.json`: `ascii` has zero non-ASCII, `unicode` has zero PUA but keeps box-drawing, `nerdfont` is unchanged, and all four have identical per-line visible widths.
- [ ] 5.3 Optional visual check: `make demo/img` per mode + `yas-demo-text` diff against the `nerdfont` baseline to confirm no column drift.
