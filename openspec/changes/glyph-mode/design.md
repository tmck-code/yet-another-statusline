## Context

The renderer composes a fully-styled string in `app.render`, then (today) optionally runs `out.translate(ASCII_TRANSLATE)` when `Config.ascii_mode` is set. `ASCII_TRANSLATE` is a `{codepoint: ascii-char}` map built from `ASCII_GLYPHS` in `constants.py` and covers every non-ASCII glyph the statusline emits. All of the statusline's own glyphs are visible width 1 (verified by prior audits — PUA icons, box-drawing, blocks, arrows, punctuation), and the box geometry is hand-tuned around that. `render/text.py` owns the width model: `_is_wide(ch)` returns `True` only for the emoji plane `U+1F300–U+1FAFF` (minus Supplemental Arrows-C), and `_visible_width` counts everything else — including all BMP symbols and PUA — as width 1.

This change generalizes the single boolean into a four-value enum, keeping the same single-seam application model.

## Goals / Non-Goals

**Goals:**
- One enum knob `glyph_mode ∈ {nerdfont, ascii, unicode, singlewidth}`, default `nerdfont`, resolved through the existing CLI → env → toml → default chain.
- Each mode is a single, total transform applied once at the `app.render` seam. Modes are **mutually exclusive** (one enum value), never stacked.
- Preserve the column-math invariant: every transform keeps each rendered line's `_visible_width` unchanged.
- Reuse the existing `ASCII_TRANSLATE` table verbatim for `ascii`.

**Non-Goals:**
- No stacking/composition of modes (e.g. "unicode + singlewidth" in one setting) — deferred; a single enum keeps the contract simple.
- No backward-compat alias for `YAS_ASCII_MODE` — it shipped days ago with no external consumers; this is a clean rename (BREAKING).
- `singlewidth` does **not** narrow the statusline's own width-1 glyphs (PUA included) — they are already width-1; the mode only collapses genuinely double-width *dynamic* content.
- Not attempting semantic transliteration of arbitrary emoji/CJK (e.g. 🔥→"fire"); singlewidth folds to a width-1 placeholder when no narrow form exists.

## Decisions

### 1. Config: enum knob replacing the boolean
`Config.ascii_mode: bool` → `Config.glyph_mode: str` (default `'nerdfont'`). New `_parse_glyph_mode(raw, origin)` accepts a case-insensitive member of the four-value set and raises `ValueError` otherwise (so an invalid value falls back to the default and is recorded, exactly like `bg_shift`/`theme`). Resolution source order: `cli_src('glyph_mode')` + `_env_sources(env, 'YAS_GLYPH_MODE')` + `toml_src(appearance, 'glyph_mode')`. `_parse_argv` gains `--glyph-mode <v>` / `--glyph-mode=<v>` and loses `--ascii-mode`. The `ascii_mode` field, its resolve block, and the `YAS_ASCII_MODE` env source are removed.

### 2. Dispatch at the seam
`app.render` replaces `ascii_mode: bool | None` with `glyph_mode: str | None = None`, falling back to the internally-loaded `cfg.glyph_mode` when the caller passes nothing (so `mon.py` keeps working unchanged via env/toml). The return becomes:
```
out = '\n'.join(render_layout(spec, r))
return apply_glyph_mode(out, glyph_mode)
```
`apply_glyph_mode(s, mode)` lives in `render/text.py` and dispatches:
- `nerdfont` → `s` (identity; no pass — the default path pays nothing).
- `ascii` → `s.translate(ASCII_TRANSLATE)` (unchanged behavior).
- `unicode` → `s.translate(UNICODE_TRANSLATE)`.
- `singlewidth` → `to_singlewidth(s)`.

`main()` passes `glyph_mode=cfg.glyph_mode`.

### 3. `unicode` mode — PUA-only translate map
`UNICODE_PUA` in `constants.py` maps each **PUA** glyph constant (the 21 `ICON_*`/`GLYPH_*` icons + `BarChars.MID`) to a non-PUA, width-1 BMP replacement; `UNICODE_TRANSLATE = {ord(g): u for g, u in UNICODE_PUA.items()}`. Box-drawing, block/sparkline, arrow, and punctuation glyphs are deliberately **absent** — they are standard Unicode and stay intact. Replacement chars are drawn from Geometric Shapes (`U+25xx`), Arrows (`U+21xx`), and plain technical/punctuation symbols that are reliably text-presentation width-1; emoji-presentation symbols (⚡ U+26A1, ⚙ U+2699, ⌛ U+231B, ✉ U+2709, …) are avoided because many terminals render them double-width even though our `_visible_width` counts them as 1. Decided mapping (apply-time may swap any char that proves wide on a real terminal — it is a one-line table edit, geometric-shape-preferred):

| PUA constant | meaning | unicode repl | codepoint |
|---|---|---|---|
| `ICON_COST` | currency-usd | `$` | U+0024 (ASCII, unambiguous) |
| `ICON_TOK_RATE` | gauge | `◷` | U+25F7 |
| `GLYPH_MODEL` | monitor-dashboard | `▦` | U+25A6 |
| `GLYPH_THINKING` | brain | `◍` | U+25CD |
| `GLYPH_BURN_FAST` | zap | `↯` | U+21AF |
| `GLYPH_BURN_SLOW` | flame | `∿` | U+223F |
| `GLYPH_FOLDER` | folder | `▭` | U+25AD |
| `GLYPH_SUBAGENT` | tasks | `☰` | U+2630 |
| `GLYPH_TASKS` | clipboard-check | `▤` | U+25A4 |
| `GLYPH_TASK_PENDING` | circle | `○` | U+25CB |
| `GLYPH_TASK_ACTIVE` | arrow-right | `▸` | U+25B8 |
| `GLYPH_TASK_DONE` | check-circle-fill | `◉` | U+25C9 |
| `GLYPH_SKILLS` | skills | `◆` | U+25C6 |
| `GLYPH_PLUGINS` | plug | `⌁` | U+2301 |
| `GLYPH_HELPER` | star-circle | `★` | U+2605 |
| `GLYPH_TRASH` | trash-can | `⌫` | U+232B |
| `GLYPH_RENAMED` | file-move | `⇄` | U+21C4 |
| `GLYPH_REPLYING` | message | `»` | U+00BB |
| `GLYPH_HOURGLASS` | hourglass | `⧖` | U+29D6 |
| `GLYPH_PIE` | pie-chart | `◕` | U+25D5 |
| `GLYPH_CACHE` | cache | `↻` | U+21BB |
| `BarChars.MID` | progress sep | `▪` | U+25AA |

### 4. `singlewidth` mode — scanning fold, not a translate map
`str.translate` cannot make width-conditional decisions, so `to_singlewidth(s)` in `render/text.py` walks the string char-by-char (ANSI escape bytes are ASCII, so `_is_wide` is `False` for them and they pass through untouched — no special escape handling needed). For each `ch`:
1. if not `_is_wide(ch)`: keep it.
2. else try `unicodedata.normalize('NFKC', ch)`; if it yields a single non-wide char (e.g. Fullwidth Forms `U+FF01–FF5E` → ASCII), use it.
3. else emit `SINGLEWIDTH_PLACEHOLDER` (`·`, U+00B7 — already a constant, width-1).

Because the statusline's own glyphs are never `_is_wide`, this is a no-op on the frame/icons and only collapses wide *dynamic* content (emoji in a branch name, CJK in a path). `singlewidth` therefore still needs a Nerd Font for the icons — it solves the wide-content alignment problem, not the missing-font problem.

### 5. Tests & invariant
`test/test_ascii_render.py` becomes the glyph-mode suite: parametrize over the four modes asserting, for each, per-line `_visible_width` equals the `nerdfont` render at widths 50/70/160. Mode-specific extra assertions: `ascii` → zero codepoints ≥ 128; `unicode` → zero PUA codepoints (both ranges) but box/block/arrow glyphs preserved; `singlewidth` → with a wide char injected into dynamic content (branch/cwd), output contains no `_is_wide` char and width is preserved. Plus a coverage guard that every PUA constant has a `UNICODE_PUA` entry, and `test_config.py` enum resolution (env/toml/cli/default + invalid-falls-back).

## Risks / Trade-offs

- **BREAKING rename**: `YAS_ASCII_MODE=1` stops working; users migrate to `YAS_GLYPH_MODE=ascii`. Acceptable given the knob is days old. The error row / `YAS_DEBUG` path already surfaces an unknown value falling back to default, so a stale `YAS_ASCII_MODE` simply has no effect (the new knob defaults to `nerdfont`).
- **Emoji-presentation width drift (unicode mode)**: a replacement BMP symbol that a particular terminal renders width-2 would visually misalign even though `_visible_width` (and the test) think it is width-1. Mitigated by preferring Geometric-Shapes/Arrows; residual risk is per-terminal and fixable with a one-line table swap. CI cannot assert real-terminal cell width.
- **Lossy singlewidth folding**: a CJK path or emoji with no NFKC narrow form collapses to `·`, harming readability. This is inherent to "fold double-width → single-width" and is opt-in; documented as the mode's trade-off.
- **Two divergent tables to maintain**: a newly-added PUA glyph now needs entries in both `ASCII_GLYPHS` and `UNICODE_PUA`. The coverage guard test fails the build if either is missing, so drift is caught immediately.
