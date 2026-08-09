## 0. Baseline

- [ ] 0.1 Capture the visual baseline BEFORE any renderer edit: `make demo/img && .claude/skills/yas-demo-text/scripts/demo-text.sh && cp -r demo/text /tmp/yas-base`. Run via the `verifier` agent, not the main thread.
- [ ] 0.2 Note the baseline pytest pass count (`make test`, via `verifier`).
- [ ] 0.3 Read `demo/prototype_openspec_authoring.py` `variant_a4` (lines 336-414) and `_a3_glyph` (lines 255-270) — that code is the reference for the rendering. Do NOT promote it verbatim; it targets `width - 3` (no gutter), uses a `max(eff_name_w, 1)` clamp instead of dropping the row, and colours nothing on the gradient.

## 1. Constants (`claude/yas/constants.py`)

- [x] 1.1 Near the other width thresholds (around `TOKENS_COST_MIN_WIDTH`, line ~55) add:
      `AUTHORING_STAGE_LABEL_W = {'proposal': 8, 'design': 6, 'deltas': 10, 'tasks': 5}` with a comment stating the widths are **constant regardless of state** and that stacked-row alignment breaks silently if any of them becomes state-dependent (design.md Decision 7).
- [x] 1.2 Add `AUTHORING_NAME_FLOOR = 15` — minimum visible columns for the name cell before the stage cells degrade to glyphs-only.
- [x] 1.3 Add `AUTHORING_ROW_MIN_WIDTH` — the box width below which even the glyph-only tier leaves the name cell non-positive. Derive it from the cell arithmetic rather than hardcoding a magic number: glyph-only block + leading divider is `4 * 1 + 4 * 3 = 16` columns, content budget is `width - 4`, so the floor is `16 + 4 + 1 = 21`. Write the derivation in the comment.
- [x] 1.4 Add `AUTHORING_STAGE_ORDER = ('proposal', 'design', 'deltas', 'tasks')`.
- [x] 1.5 **No new glyph constants.** Confirm `GLYPH_WF_DIVIDER` (line 183), `GLYPH_TASK_PENDING`/`ACTIVE`/`DONE` (lines 168-170) and `ELLIPSIS` (line 233) already exist and already have `ASCII_GLYPHS` / `UNICODE_PUA` / `GITHUB_ICON_OVERRIDE` entries. Verify every substitution for those four glyphs is width 1 in all four glyph modes — a width-2 substitute breaks the alignment invariant.

## 2. Gather: `claude/yas/info/openspec.py`

- [x] 2.1 Add an `AuthoringChange` slots class with `__slots__ = ('name', 'has_proposal', 'has_design', 'delta_count', 'delta_total')`, plus `__init__`, `__eq__` (with the `NotImplemented` guard the existing `OpenSpec.__eq__` uses), `__hash__ = None`, and `__repr__` — matching the module's existing style, not a `NamedTuple`.
- [x] 2.2 Extend `OpenSpec.__slots__` (line 8) to `('changes', 'authoring')`; add `authoring: list[AuthoringChange] | None = None` to `__init__` defaulting to `[]`; include it in `__eq__` and `__repr__`. `changes` keeps its exact `list[tuple[str, int, int]]` shape.
- [x] 2.3 Add a module-level `_parse_delta_total(proposal_path: Path) -> int`: read the file (swallow `OSError`), scan for the `## Capabilities` heading, then count lines matching `^\s*-\s+`` `[a-z0-9-]+` ``` (a bullet whose first token is a backticked kebab-case name) until the next `^## ` heading. Return 0 on any failure. Compile the two regexes at module level alongside the existing `open_re`/`done_re` style.
- [x] 2.4 In `from_cwd`, after the existing `rglob('tasks.md')` loop (line 31-43) and before `return`, add the authoring pass over `sorted((Path(root) / 'changes').iterdir())` guarded by `if (Path(root) / 'changes').is_dir()`:
      skip non-dirs, names starting with `.`, and `name == 'archive'`;
      skip when `(d / 'tasks.md').is_file()`;
      otherwise build an `AuthoringChange` with `has_proposal=(d / 'proposal.md').is_file()`, `has_design=(d / 'design.md').is_file()`, `delta_count=len(list(d.glob('specs/*/spec.md')))`, `delta_total=_parse_delta_total(d / 'proposal.md')`.
      Wrap the `iterdir` in `try/except OSError` and fall back to an empty list.
- [x] 2.5 Add a comment at the top of the authoring pass stating the disjointness invariant (a dir with `tasks.md` is handled by the first pass only) and that an empty-checkbox `tasks.md` is deliberately invisible in BOTH passes — existing behaviour, not an oversight (design.md Decision 1).
- [x] 2.6 Do NOT change the existing loop's `if total == 0: continue`, the `/archive/` skip, or the returned tuple shape.

## 3. Gather seam: `claude/yas/info/__init__.py`

- [ ] 3.1 Import `AuthoringChange` alongside `OpenSpec` (line 15).
- [ ] 3.2 Refactor so the walk happens once: add a private `@cached_property _openspec(self) -> OpenSpec` returning `OpenSpec.from_cwd(self.session.cwd)`, and change `changes` (line 118-120) to `return self._openspec.changes`.
- [ ] 3.3 Add `@cached_property authoring_changes(self) -> list[AuthoringChange]` returning `self._openspec.authoring`, with a docstring noting it is disjoint from `changes` and shares the same single walk.
- [ ] 3.4 Confirm nothing in `build_narrow` / `build_medium` reads either property, so the laziness requirement in the `statusline-info` delta still holds.

## 4. Renderer: `claude/yas/renderer.py`

- [ ] 4.1 Add `def openspec_authoring_row(self, change: AuthoringChange, box_width: int, fill: float = 1.0) -> tuple[str, tuple[int, ...]]` near `openspec_bar` (line 2015). Return `('', ())` when `box_width < AUTHORING_ROW_MIN_WIDTH` so the builder can drop the row (design.md Decision 9) — do NOT clamp the name width to 1 the way the prototype does.
- [ ] 4.2 Private helper `_authoring_glyph(self, change, slot) -> str`: compute the per-slot done/active/pending state per design.md Decision 3 (first not-done slot in `AUTHORING_STAGE_ORDER` is active; `tasks` is never done; `deltas` done iff `delta_count >= delta_total > 0`), and return `f'{self.safe}{GLYPH_TASK_DONE}{RESET}'` / `f'{self.yellow}{GLYPH_TASK_ACTIVE}{RESET}'` / `f'{self.LABEL}{GLYPH_TASK_PENDING}{RESET}'`.
- [ ] 4.3 Private helper `_authoring_label(self, change, slot) -> str`: `deltas` → `f'deltas {n}/{m}'` where `n = min(change.delta_count, 9)` and `m = '?' if change.delta_total <= 0 and change.delta_count == 0 else min(max(change.delta_total, change.delta_count), 9)`; every other slot → the slot name. Then `text[:w].ljust(w)` with `w = AUTHORING_STAGE_LABEL_W[slot]`. Assert (or comment) that the result is always exactly `w` columns.
- [ ] 4.4 Build the row in TWO passes (design.md Decision 6 — colours depend on columns, columns depend on widths):
      **Pass 1** assemble the row with a sentinel placeholder for each divider (use a single non-PUA, non-ANSI char that cannot occur in a name, e.g. `'\x00'`, and document why): `name_field + SENTINEL + cell0 + SENTINEL + cell1 + SENTINEL + cell2 + SENTINEL + cell3`, where the divider's full visible form is `' ┊ '` — so the sentinel stands for the `┊` and the two surrounding spaces are literal.
      **Pass 2** locate each sentinel's 0-indexed visible offset in the ANSI-stripped string, compute `col = 3 + off`, and replace the sentinel with `f'{self.grad_at(col - 1, box_width, fill=fill)}{GLYPH_WF_DIVIDER}{RESET}'`. Return the tuple of cols.
- [ ] 4.5 Width budget: `content_budget = box_width - 4` (NOT `- 3`) so `border_line`'s own padding yields the one-space right gutter (design.md Decision 8, spec requirement "One-space right gutter"). Never append a literal trailing space.
- [ ] 4.6 Cell widths: cell = glyph + `' '` + label, so full-label cells are 10/8/12/7 = 37 columns; four `' ┊ '` dividers add 12; block+leading-divider = 49. `name_field_w = content_budget - 49`. If `name_field_w >= AUTHORING_NAME_FLOOR` use full labels; else use glyph-only cells (block+divider = 16) and `name_field_w = content_budget - 16`.
- [ ] 4.7 Name cell: `f'{CLR_WHITE_BRT}{ITALIC}{title}{RESET}{self.R}'` padded with spaces to `name_field_w`; truncate to `name_field_w - 1` visible columns plus `ELLIPSIS` when it does not fit. All measurement via `_visible_width`, never `len()`.
- [ ] 4.8 Assert-by-construction at the end of the method (a comment plus a cheap `_visible_width(line_content) == content_budget` check in the tests, not a runtime `assert` in the render path).

## 5. Layout wiring: `claude/yas/layout.py`

- [ ] 5.1 In `build_wide`, near the existing `openspec_bars` construction (lines 749-751), add:
      `authoring = view.authoring_changes` and
      `authoring_rows = [r.openspec_authoring_row(c, width, fill=fill) for c in authoring]`, then filter out entries whose line is empty (the sub-minimum-width drop).
- [ ] 5.2 Derive `stage_cols` from the FIRST surviving authoring row and add a `assert`-free consistency comment; all rows share the same columns by construction (design.md Decision 7). The alignment is asserted in tests, not at runtime.
- [ ] 5.3 Leave `title_w` (line 750) computed from `changes` only — authoring rows own their own name-cell arithmetic and must not influence the task bars' title width.
- [ ] 5.4 Rewrite the openspec block at lines 1334-1341:
      condition becomes `if openspec_bars or authoring_rows:`;
      leading row stays `RowSpec(sep_kind('separator'), ups=pending_ups + tail_ups, labels=spec_labels)` but gains `downs=stage_cols` when `authoring_rows` is non-empty;
      then one `RowSpec('content', content=line)` per authoring row;
      then, when both groups exist, `RowSpec('separator_dim', ups=stage_cols)` between them (a NEW separator — today the block has none between rows);
      then the task bars as today;
      then `RowSpec('bottom_border')`, or `RowSpec('bottom_border', ups=stage_cols)` when the authoring group is the last thing in the box.
- [ ] 5.5 Add a comment at the wiring site recording that these `┊` dividers deliberately DO carry `┬`/`┴` elbows, unlike the workflow two-column divider documented at lines 1324-1328, and why (design.md Decision 5).
- [ ] 5.6 Do NOT touch `build_narrow` (line 531) or `build_medium` (line 604) — the openspec section is wide-only and stays so.
- [ ] 5.7 No new `render_layout` kind: `RowSpec('content', ...)` covers it. (Note `render_layout` has no `else` branch, so an unrecognised kind renders nothing silently.)

## 6. Tests

- [ ] 6.1 `test/test_layout_seam.py`: extend `_silence_dynamic` (lines 52-70) so the `OpenSpec.from_cwd` stub also returns an empty `authoring` list — `classmethod(lambda cls, cwd: openspec_mod.OpenSpec(changes=[], authoring=[]))`. Without this every seam test starts depending on whatever is mid-authoring in the working tree (design.md Risks).
- [ ] 6.2 New `test/test_openspec_authoring.py`, gather half, using `tmp_path` fixtures that build real `openspec/changes/<name>/` trees:
      (a) scaffolded dir with only `.openspec.yaml` → one `AuthoringChange`, all flags false, `delta_count == 0`;
      (b) dir with `tasks.md` containing checkboxes → absent from `authoring`, present in `changes`;
      (c) dir with a zero-checkbox `tasks.md` → absent from BOTH;
      (d) `changes/archive/...` without `tasks.md` → excluded;
      (e) dotfile dir and a stray file in `changes/` → skipped;
      (f) `delta_count` counts `specs/*/spec.md` and not `specs/*/other.md`;
      (g) `_parse_delta_total` returns the number of backticked capability bullets across New + Modified, stops at the next `## ` heading, and returns 0 for a missing/malformed proposal.
- [ ] 6.3 Same file, render half (construct the `AuthoringChange` directly, no filesystem):
      (a) row is exactly `box_width` visible columns after `border_line` wrapping, at widths 90, 100, 120 and at the glyph-only widths;
      (b) exactly one space sits between the last `tasks` label character and the closing `│`;
      (c) the four `┊` columns in the ANSI-stripped line equal the returned `cols` tuple;
      (d) **alignment matrix** — 3 names of very different lengths × 5 lifecycle stages, all at one width, all returning the identical `cols` tuple (this is the load-bearing invariant; name the test so its purpose is unmistakable);
      (e) `deltas 0/3` vs `deltas 3/3` produce identical widths and identical `cols`;
      (f) glyph-only degrade: below the name-cell floor the labels are gone but four `┊` remain and `cols` still has four entries;
      (g) below `AUTHORING_ROW_MIN_WIDTH` the helper returns `('', ())`;
      (h) a name longer than the cell is truncated and ends with `ELLIPSIS`, with `cols` unchanged from the short-name case;
      (i) stage-state matrix: scaffolded / proposal-only / design-done / deltas-partial / deltas-complete each yield the expected done/active/pending glyph sequence;
      (j) unknown denominator renders `deltas 0/?` and `delta_count > delta_total` renders a clamped equal fraction.
- [ ] 6.4 Divider-gradient test: for each divider column `col`, assert the ANSI run immediately preceding that `┊` in the raw (unstripped) line equals `r.grad_at(col - 1, width, fill=fill)`. This is the only mechanical check that the gradient requirement did not silently regress to a flat colour.
- [ ] 6.5 `test/test_layout_seam.py`: with a stubbed `authoring` list of 2 changes and no task bars, assert the emitted row kinds are `separator` → 2 × `content` → `bottom_border`, that the separator's `downs` and the bottom border's `ups` both equal the rows' `cols`, and that the `specs` caption is present. Then with both groups present, assert the extra `separator_dim` appears between them carrying `ups=cols`.
- [ ] 6.6 `test/test_layout_seam.py`: assert `build_narrow` and `build_medium` emit no authoring content even when `authoring_changes` is non-empty.
- [ ] 6.7 Laziness test (extend `test/test_info.py`): reading only `view.subagents` triggers no `openspec/changes/` enumeration; reading both `view.changes` and `view.authoring_changes` walks once.
- [ ] 6.8 Glyph-mode test: render one authoring row per `glyph_mode` (`nerdfont`, `ascii`, `unicode`, `github`) and assert the visible width and the `cols` tuple are identical in all four — this is what guards the width-1-substitution requirement from task 1.5.
- [ ] 6.9 Run the full gate via the `verifier` agent (`make test`, then `uv run ruff check`). Never on the main thread.

## 7. Visual gate and docs

- [ ] 7.1 Add a demo scenario covering the authoring row (extend the `openspec` scenario or add `openspec-authoring`): at least one change mid-authoring alongside at least one task bar, so the group ordering, the inter-group `separator_dim` and the elbows are all exercised. Include one short and one over-long change name so truncation is visible.
- [ ] 7.2 Re-golden: `make demo/img && .claude/skills/yas-demo-text/scripts/demo-text.sh && diff -ru /tmp/yas-base demo/text`. Every diff outside the openspec box is a regression — review for column drift, not just content change.
- [ ] 7.3 Eyeball `make demo`: every `┬` above an authoring row lines up with its `┊` and its `┴`, and the divider colours flow with the border gradient rather than standing out flat.
- [ ] 7.4 `CONTEXT.md`: add glossary entries for **Authoring Stage** (a change scaffolded but without `tasks.md`), the four stage slots and their glyph vocabulary, and a note that the deltas denominator is derived from the proposal's declared capabilities and shows `?` until `proposal.md` exists.
- [ ] 7.5 Delete `demo/prototype_openspec_authoring.py` — it is explicitly marked throwaway ("delete after the design call is made") and its A4 design has now shipped.
