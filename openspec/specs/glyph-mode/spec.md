# glyph-mode Specification

## Purpose

Define the glyph-rendering contract: what each of the three modes `nerdfont` / `ascii` / `unicode` does to the rendered output, the orthogonal `single_width` fold that composes with any mode, the column-math (visible width) invariant every mode and the fold must hold, and the single-seam application model (mode transform first, then the fold) that every render entry point inherits.

## Requirements

### Requirement: Three glyph rendering modes

The statusline SHALL support exactly three mutually-exclusive glyph rendering modes, selected by the `glyph_mode` configuration knob: `nerdfont`, `ascii`, and `unicode`. Each mode SHALL be a single total transform applied to the fully-rendered statusline string. The default mode SHALL be `nerdfont`.

- `nerdfont` SHALL display every character unchanged (identity transform; full fidelity, requires a Nerd Font).
- `ascii` SHALL replace every non-ASCII character the statusline emits with a width-1 ASCII equivalent, producing output containing only codepoints below U+0080.
- `unicode` SHALL replace only Nerd Font Private Use Area (PUA) icon glyphs with non-PUA, width-1 Unicode equivalents, leaving box-drawing, block/sparkline, arrow, and punctuation glyphs unchanged.

#### Scenario: Nerdfont mode is identity

- **WHEN** `glyph_mode` is `nerdfont` and `single_width` is false
- **THEN** the rendered output is byte-for-byte identical to the untransformed render

#### Scenario: Ascii mode produces only ASCII

- **WHEN** `glyph_mode` is `ascii`
- **THEN** the rendered output contains no codepoint at or above U+0080

#### Scenario: Unicode mode removes PUA but keeps other Unicode

- **WHEN** `glyph_mode` is `unicode`
- **THEN** the output contains no Private Use Area codepoint (U+E000–U+F8FF or U+F0000–U+FFFFD)
- **AND** box-drawing, block, and arrow glyphs are still present unchanged

### Requirement: Orthogonal single-width folding

The statusline SHALL expose a `single_width` boolean knob, independent of `glyph_mode`, that folds every double-width character in the rendered output to a width-1 equivalent, leaving all already-width-1 characters (including the statusline's own PUA glyphs) unchanged. When enabled, the fold SHALL be applied after the selected glyph mode's transform, so it composes with any mode. The default SHALL be false (no fold).

#### Scenario: Single-width folds wide dynamic content

- **WHEN** `single_width` is true and dynamic content (e.g. a git branch name or cwd path) contains a double-width character
- **THEN** that character is replaced by a width-1 equivalent and the output contains no double-width character
- **AND** the statusline's own width-1 glyphs are left unchanged

#### Scenario: Single-width composes with nerdfont

- **WHEN** `glyph_mode` is `nerdfont` and `single_width` is true
- **THEN** the statusline's PUA icons are preserved unchanged
- **AND** any double-width dynamic content is folded to width-1

#### Scenario: Single-width composes with unicode

- **WHEN** `glyph_mode` is `unicode` and `single_width` is true
- **THEN** PUA icons are replaced by their non-PUA Unicode equivalents
- **AND** any double-width dynamic content is folded to width-1

### Requirement: Column-math preservation across modes

Every glyph **mode** SHALL preserve column geometry: for any session and render width, each output line's visible width (per the renderer's width model) SHALL equal the visible width of the same line rendered in `nerdfont` mode. No mode SHALL move a border, elbow, or divider. The `single_width` fold is the deliberate exception — it narrows genuinely double-width dynamic content from two cells to one, so for content the width model counts as wide it intentionally changes that model's measured width. Its purpose is to make such content align on terminals whose font renders those glyphs as single cells; it is a no-op on the statusline's own already-width-1 chrome, which it never shifts.

#### Scenario: Visible width is mode-invariant

- **WHEN** the same session (with no genuinely double-width dynamic content) is rendered at a given width in each of the three modes, with `single_width` false
- **THEN** every line's visible width is identical across all three modes

#### Scenario: Fold leaves width-1 chrome unmoved

- **WHEN** a session is rendered with `single_width` true and its dynamic content contains no double-width character
- **THEN** every line's visible width is identical to the same render with `single_width` false

### Requirement: Single-seam application

The selected glyph mode and the `single_width` fold SHALL be applied exactly once each, at the final render boundary, after the layout is fully composed — the mode transform first, then the fold when enabled. The `nerdfont` mode with `single_width` false SHALL incur no transformation pass. Callers that do not specify a mode or fold SHALL inherit the resolved `glyph_mode` / `single_width` configuration values, so all render entry points (the statusline command and the multi-session observer) honor both knobs without per-call wiring.

#### Scenario: Observer honors the knobs without explicit wiring

- **WHEN** `YAS_GLYPH_MODE=ascii` is set and the multi-session observer renders a session
- **THEN** that session's box is rendered in ascii mode

#### Scenario: Observer honors single-width without explicit wiring

- **WHEN** `YAS_GLYPH_SINGLE_WIDTH=1` is set and the multi-session observer renders a session
- **THEN** that session's box has its double-width dynamic content folded to width-1
