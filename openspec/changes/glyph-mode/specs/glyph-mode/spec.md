## ADDED Requirements

### Requirement: Four glyph rendering modes

The statusline SHALL support exactly four mutually-exclusive glyph rendering modes, selected by the `glyph_mode` configuration knob: `nerdfont`, `ascii`, `unicode`, and `singlewidth`. Each mode SHALL be a single total transform applied to the fully-rendered statusline string. The default mode SHALL be `nerdfont`.

- `nerdfont` SHALL display every character unchanged (identity transform; full fidelity, requires a Nerd Font).
- `ascii` SHALL replace every non-ASCII character the statusline emits with a width-1 ASCII equivalent, producing output containing only codepoints below U+0080.
- `unicode` SHALL replace only Nerd Font Private Use Area (PUA) icon glyphs with non-PUA, width-1 Unicode equivalents, leaving box-drawing, block/sparkline, arrow, and punctuation glyphs unchanged.
- `singlewidth` SHALL replace every double-width character in the rendered output with a width-1 equivalent, leaving all already-width-1 characters (including the statusline's own PUA glyphs) unchanged.

#### Scenario: Nerdfont mode is identity

- **WHEN** `glyph_mode` is `nerdfont`
- **THEN** the rendered output is byte-for-byte identical to the untransformed render

#### Scenario: Ascii mode produces only ASCII

- **WHEN** `glyph_mode` is `ascii`
- **THEN** the rendered output contains no codepoint at or above U+0080

#### Scenario: Unicode mode removes PUA but keeps other Unicode

- **WHEN** `glyph_mode` is `unicode`
- **THEN** the output contains no Private Use Area codepoint (U+E000–U+F8FF or U+F0000–U+FFFFD)
- **AND** box-drawing, block, and arrow glyphs are still present unchanged

#### Scenario: Singlewidth mode collapses wide dynamic content

- **WHEN** `glyph_mode` is `singlewidth` and dynamic content (e.g. a git branch name or cwd path) contains a double-width character
- **THEN** that character is replaced by a width-1 equivalent and the output contains no double-width character
- **AND** the statusline's own width-1 glyphs are left unchanged

### Requirement: Column-math preservation across modes

Every glyph mode SHALL preserve column geometry: for any session and render width, each output line's visible width SHALL equal the visible width of the same line rendered in `nerdfont` mode. No mode SHALL move a border, elbow, or divider.

#### Scenario: Visible width is mode-invariant

- **WHEN** the same session is rendered at a given width in each of the four modes
- **THEN** every line's visible width is identical across all four modes

### Requirement: Single-seam application

The selected glyph mode SHALL be applied exactly once, at the final render boundary, after the layout is fully composed. The `nerdfont` mode SHALL incur no transformation pass. Callers that do not specify a mode SHALL inherit the resolved `glyph_mode` configuration value, so all render entry points (the statusline command and the multi-session observer) honor the knob without per-call wiring.

#### Scenario: Observer honors the knob without explicit wiring

- **WHEN** `YAS_GLYPH_MODE=ascii` is set and the multi-session observer renders a session
- **THEN** that session's box is rendered in ascii mode
