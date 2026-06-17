## 1. Config knob

- [x] 1.1 Add `DEFAULT_LABELS = False` to `claude/yas/constants.py`
- [x] 1.2 Add `labels: bool = DEFAULT_LABELS` field to the `Config` dataclass in `claude/yas/config.py`
- [x] 1.3 Resolve `labels` via `_resolve('labels', _env_sources(env, 'YAS_LABELS') + toml_src(layout, 'labels'), _parse_bool, DEFAULT_LABELS, …)` and pass `labels=labels` into the `Config(...)` constructor
- [x] 1.4 Add config tests: default `false`, `[layout].labels=true` enables, `YAS_LABELS=0` overrides the file, invalid value falls through to `false`

## 2. Superscript primitive

- [x] 2.1 Add `superscript(s: str) -> str` to `claude/yas/render/text.py` with a module-level ASCII→superscript map (letters, digits, `+`, `/`, space), passing unmapped characters through unchanged
- [x] 2.2 Add tests asserting `superscript('cache')`/`superscript('5h')` map correctly, an unmapped character passes through, and `_visible_width(superscript(s)) == len(s)` for the label vocabulary

## 3. Border label overlay

- [x] 3.1 Refactor `border_top` to build a per-column `chars` buffer (corners, fill, elbows, session id) plus a fill-only mask, then run the existing single ordered `grad_at(col) + chars[col]` pass over the buffer
- [x] 3.2 Apply the same buffer refactor to `border_separator` and `border_separator_dim`, preserving the dim factor per column
- [x] 3.3 Add a `labels: tuple[tuple[str, int], ...] = ()` parameter to the three methods; overlay each `(text, start_col)` left-to-right across contiguous fill columns only, mapping text through `superscript`, truncating at the first non-fill column and dropping when the anchor is not fill
- [x] 3.4 Confirm a pill-active row never has pill columns overwritten by a label
- [x] 3.5 Add border tests: a labelled row equals its label-free counterpart except at overlaid columns; label truncates before an elbow; label dropped at session id / non-fill anchor; label glyphs carry the per-column gradient (and dim) colour

## 4. Layout wiring

- [x] 4.1 Add `labels: list[tuple[str, int]] = field(default_factory=list)` to `RowSpec` in `claude/yas/layout.py`
- [x] 4.2 In `build_wide`, when `view.cfg.labels`, compute label start columns from existing variables (`path_div_col`, `helper_anchor` + helper sub-widths, `sep_rate_col`, `cache_div_col`, tokens/cost vsep columns) for the top border and each separator, and attach them to the corresponding `RowSpec.labels`
- [x] 4.3 Thread `labels=row.labels` through `render_layout` into `border_top` / `border_separator` / `border_separator_dim`
- [x] 4.4 Add a layout-seam test constructing a wide `SessionView` with `Config(labels=True)` asserting the expected labels appear on the right rows, and that `Config(labels=False)` output is unchanged

## 5. Measured-anchor refactor and per-value labels

- [x] 5.1 Replace the tuned-offset placement in `build_wide` with content-column measurement: strip ANSI from each row's rendered string and locate values by their whitespace-delimited token offsets, bounded by the existing divider/width variables
- [x] 5.2 Add the `changes` label over the git dirty block (`•N*M`), emitted only when that block is present
- [x] 5.3 Add the 5h sub-value labels: `5h` over the glyph plus `remain`/`used`/`burn rate` in full form, and only `5h` + `used` in the compact/reset form
- [x] 5.4 Add the 7d sub-value labels: `7d` over the glyph plus `used`, and `burn rate` when a trend is rendered
- [x] 5.5 Add the context-separator labels `tokens` (over the token count), `limit` (over the context-window percent), and `until dumb` (over the compaction-risk percent)
- [x] 5.6 Carry the ` sess/day` suffix on the tokens-separator labels: `input sess/day`, `cache sess/day`, `output sess/day`, `cost sess/day`
- [x] 5.7 Emit the elapsed-cell `clear` label only when the clear timer is displayed (clear content non-empty); when absent emit only `session` over the single timer, both anchored by measuring the rendered elapsed content
- [x] 5.8 Add the dynamic-section separator captions at content start (like `skills + plugins`): `plan` (todo-checklist / task row), `subagents` (subagent cohort), `workflow` (workflow cohort), `specs` (OpenSpec change bars); in the side-by-side checklist+subagents block place `plan` at content start and `subagents` over the right column
- [x] 5.9 Update `test/test_labels.py` / `test/test_labels_layout.py` for the measured anchors and the new label set

## 6. Docs and verification

- [x] 6.1 Document `[layout].labels` (and `YAS_LABELS`) in `yas.example.toml`
- [x] 6.2 Update the `CONTEXT.md` glossary with the section-label terms (value labels, `until dumb`, `limit`) if any displayed term changed
- [x] 6.3 Run `make test` (green, baseline + new tests) and `make demo` with labels on across the narrow→medium→wide thresholds; eyeball elbow alignment, gradient continuity, and label placement
