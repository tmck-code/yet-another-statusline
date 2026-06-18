## ADDED Requirements

### Requirement: Opt-in wide-only label activation

The statusline SHALL paint superscript section labels onto the wide layout's border and separator rows only when `cfg.labels` is `true`. When `cfg.labels` is `false` the layout SHALL render identically to today. The narrow and medium layouts SHALL ignore `cfg.labels` entirely and never paint labels.

#### Scenario: Labels off renders unchanged

- **WHEN** `cfg.labels` is false in the wide layout
- **THEN** the border and separator rows render identically to the pre-feature output (no superscript glyphs present)

#### Scenario: Labels on paints the wide frame

- **WHEN** `cfg.labels` is true and the terminal width selects the wide layout
- **THEN** superscript labels appear on the top border and the separator rows above their sections

#### Scenario: Narrow and medium ignore the flag

- **WHEN** `cfg.labels` is true but the width selects the narrow or medium layout
- **THEN** no labels are painted and the output is identical to `cfg.labels` false

### Requirement: Labels anchored above the value they name

When `cfg.labels` is true, each label SHALL be positioned so that its starting column sits above the value or sub-value it names in the content row immediately below the border/separator that carries it. Label start columns SHALL be derived by measuring the already-rendered content strings that `build_wide` holds for each row — stripping ANSI and finding the whitespace-delimited token offsets — rather than from a fixed tuned-position table. A label SHALL only be emitted for a value that is actually present in the measured content. A section that displays multiple distinct sub-values MAY carry one label per sub-value, anchored over each.

The 5h cell SHALL carry `5h` over its glyph and, in its **full** form, additionally `remain` (over the reset countdown), `used` (over the used percentage), and `burn rate` (over the burn-rate trend); in its **compact/reset** form (no countdown or trend rendered) it SHALL carry only `5h` + `used`. The 7d cell SHALL carry `7d` over its glyph plus `used` (over the used percentage) and `burn rate` (over the burn-rate trend, when present). The git dirty block SHALL carry a `changes` label over the `•N*M` cluster when that block is present.

The elapsed/timers cell SHALL carry a `session` label over the session timer always, and a `clear` label over the clear timer only when the clear timer is actually displayed (its rendered content is non-empty). When no clear timer is shown only `session` SHALL be emitted, anchored over the single timer. Both timer labels SHALL be anchored by measuring the rendered elapsed content.

#### Scenario: Elapsed section carries two labels

- **WHEN** `cfg.labels` is true and the elapsed section is present with a clear time and a session time
- **THEN** the top border above it shows a `clear` label over the clear time and a `session` label over the session time

#### Scenario: Clear label omitted when no clear timer

- **WHEN** `cfg.labels` is true and the elapsed cell shows only the session timer (no `/clear` marker, clear content empty)
- **THEN** only a `session` label is emitted, anchored over the single timer, and no `clear` label appears

#### Scenario: Changes label over the git dirty block

- **WHEN** `cfg.labels` is true and the path/git section renders a dirty block (`•N*M`)
- **THEN** the top border above it shows a `changes` label anchored over that block, and when there is no dirty block no `changes` label is emitted

#### Scenario: 5h cell carries sub-value labels in full form

- **WHEN** `cfg.labels` is true and the 5h cell renders its full form (glyph, reset countdown, used percentage, and burn-rate trend)
- **THEN** the top border above it shows `5h` over the glyph, `remain` over the countdown, `used` over the used percentage, and `burn rate` over the trend

#### Scenario: 5h compact form omits remain and burn rate

- **WHEN** `cfg.labels` is true and the 5h cell renders its compact/reset form (no countdown or trend)
- **THEN** only `5h` and `used` are emitted, and no `remain` or `burn rate` label appears

#### Scenario: 7d cell carries used and burn-rate labels

- **WHEN** `cfg.labels` is true and the 7d cell is present with a used percentage and a burn-rate trend
- **THEN** the top border above it shows `7d` over the glyph, `used` over the used percentage, and `burn rate` over the trend; when no trend is rendered the `burn rate` label is omitted

#### Scenario: Context separator labels its columns

- **WHEN** `cfg.labels` is true and the context row is present
- **THEN** the separator above it carries a `tokens` label over the token count (e.g. `70.0K`), a `limit` label over the context-window percent (e.g. `(7%)`), and an `until dumb` label over the compaction-risk percent (e.g. `47%`)

#### Scenario: Tokens/cost separator labels its columns

- **WHEN** `cfg.labels` is true and the tokens/cost row is present
- **THEN** the separator above it carries `input sess/day`, `cache sess/day`, and `output sess/day` labels over the three token columns, a `cost sess/day` label over the cost column, and a `tokens over time` label over the sparkline column

#### Scenario: Skills separator labels the skills row

- **WHEN** `cfg.labels` is true and the skills/plugins row is present
- **THEN** the separator above it carries a `skills + plugins` label

#### Scenario: Dynamic section separators carry content-start captions

- **WHEN** `cfg.labels` is true and a dynamic section row is present
- **THEN** the separator above it carries a caption anchored at content-start (like `skills + plugins`): `plan` over the todo-checklist / task row, `subagents` over the subagent cohort, `workflow` over the workflow cohort, and `specs` over the OpenSpec change bars

#### Scenario: Side-by-side checklist and subagents split the caption

- **WHEN** `cfg.labels` is true and the checklist and subagents render in a side-by-side block
- **THEN** the separator above carries `plan` at content start and `subagents` over the right column

### Requirement: Labels colourise positionally with the border gradient

Each label glyph SHALL take the gradient colour of the column it occupies, identical to the fill character it replaces. Labels SHALL NOT be painted in a single flat colour. On dimmed separator rows each label glyph SHALL inherit the same per-column dim factor as the surrounding fill.

#### Scenario: Top-border label follows the rainbow

- **WHEN** a label occupies columns 60 through 66 of the rainbow top border
- **THEN** each of its glyphs is coloured with the gradient colour for its own column (60..66), matching the colour the fill would have had at that column

#### Scenario: Separator label inherits dim ramp

- **WHEN** a label sits on a dimmed separator row away from any elbow
- **THEN** its glyphs are dimmed by the same `_dim_for_col` factor as the adjacent dotted fill

### Requirement: Labels yield to structural glyphs

A label SHALL only overwrite fill characters (`─` on borders, `┄` on dim separators). It SHALL never overwrite an elbow (`┬`, `┴`, `┼`), the opening/closing frame corners, the embedded session id on the top border, or any column owned by an active model pill. When a label's full text would not fit in the available run of fill columns before the next structural glyph, it SHALL be truncated to fit, and if no fill columns are available it SHALL be dropped entirely. Dropping or truncating a label SHALL NOT shift any other column, elbow, or content.

#### Scenario: Label truncated before an elbow

- **WHEN** a label's text is longer than the run of fill columns between its start and the next elbow
- **THEN** the label is truncated so its last glyph sits before the elbow and the elbow is preserved

#### Scenario: Label dropped when no room

- **WHEN** there is no fill column available at a label's anchor (e.g. it collides with the session id or pill)
- **THEN** the label is omitted and all elbows, session id, pill, and column positions are unchanged

#### Scenario: Session id preserved on top border

- **WHEN** a label's anchor overlaps the embedded session id region of the top border
- **THEN** the session id is rendered intact and the label is truncated or dropped to avoid it

### Requirement: Superscript text mapping with fallback

The statusline SHALL map ASCII label text to Unicode superscript glyphs for rendering (e.g. `tokens` → `ᵗᵒᵏᵉⁿˢ`). Characters that have a defined superscript form (letters, digits, `+`, `/`, space) SHALL be mapped to that form. A character with no superscript form SHALL be passed through unchanged rather than dropped, and the mapped string SHALL have the same visible column width as the input (each glyph counting as one column).

#### Scenario: Lowercase word maps to superscripts

- **WHEN** the label text is `cache`
- **THEN** it renders as the superscript glyph sequence for `c`, `a`, `c`, `h`, `e`

#### Scenario: Digits and width preserved

- **WHEN** the label text is `5h`
- **THEN** it renders as superscript `5` followed by superscript `h`, occupying exactly two columns

#### Scenario: Unmapped character passes through

- **WHEN** a label contains a character with no defined superscript form
- **THEN** that character is emitted unchanged and the total visible width still equals the input length
