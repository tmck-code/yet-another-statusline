## Context

**Gather.** `OpenSpec.from_cwd(cwd)` (`claude/yas/info/openspec.py:23-44`) finds
the repo's `openspec/` dir by walking parents, then iterates
`sorted(Path(root).rglob('tasks.md'))`, skipping anything under `/archive/`,
counting `- [ ]` / `- [x]` lines, and — critically — `continue`-ing when
`total == 0`. It returns `changes: list[tuple[str, int, int]]` of
`(dir_name, done, total)`. It never enumerates `openspec/changes/*`, so a change
that has been scaffolded but has no `tasks.md` is structurally invisible. This is
a new enumeration path, not a tweak to the existing loop.

`SessionView.changes` (`claude/yas/info/__init__.py:118-120`) is a
`@cached_property` returning `OpenSpec.from_cwd(self.session.cwd).changes`.

**Authoring lifecycle** (ground truth: `.scratch/explore-openspec-order.md`).
`openspec new change <name>` creates the change dir and `.openspec.yaml` — the
name is fixed at that instant, before any content. Then, ~70–90 s apart:
`proposal.md` → `design.md` → 1–4 `specs/<capability>/spec.md` deltas →
`tasks.md` last. Whole pass ~6–7 min. `tasks.md` is the only artifact edited
afterwards (checkbox ticking during implementation).

**Render.** `Renderer.openspec_bar(name, done, total, box_width, title_w)`
(`renderer.py:2015-2041`) returns a plain string: a `title_w`-wide italic name
cell, a `spec_gradient_bar` whose gradient index is `zlib.crc32(name) % len(SPEC_GRADIENTS)`,
then `done/total` and a percentage. It contributes no divider columns.

**Layout.** `build_wide` (`layout.py:749-751`) computes
`title_w = min(40, title_cap, max(len(n) for n, _, _ in changes))` and builds
`openspec_bars`. At `layout.py:1334-1341` the block is emitted as
`RowSpec(sep_kind('separator'), ups=pending_ups + tail_ups, labels=[('specs', 3)])`,
then one `RowSpec('content', content=bar)` per bar, then
`RowSpec('bottom_border')` — with **no separators between the bars**. When there
are no bars, the bottom border absorbs `pending_ups + tail_ups` instead.
`build_narrow` (`layout.py:531`) and `build_medium` (`layout.py:604`) contain no
openspec references at all: the section is wide-only.

**Elbows.** `RowSpec.downs` / `.ups` (`layout.py:74-104`) carry 1-indexed border
columns into `border_top` / `border_separator` / `border_separator_dim` /
`border_bottom`. `border_line` puts content at visual column 2 (col-form 3), so a
divider at 0-indexed visible offset `off` inside the content is border column
`3 + off`.

**Gradient on an in-row divider.** Precedent exists at `layout.py:478-481`
(`build_workflow_rows`): `div_color = r.grad_at(workflow_divider_col(width) - 1, width, fill=fill)`
then `divider = f'  {div_color}{GLYPH_WF_DIVIDER}{RESET}  '`. That divider,
however, deliberately floats free of the frame — `layout.py:1324-1328` documents
that no `┬`/`┴` elbow threads it. The authoring row breaks with that convention
on purpose (Decision 5).

**Prototype.** `demo/prototype_openspec_authoring.py`, variant `A4`
(`variant_a4`, lines 364-414) is the validated design; the report at
`.scratch/yas-editor-openspec-proto-report.md` records the captured renderings
and the programmatic column-alignment verification at widths 90/60/45/35. It is
a standalone script, never routed through `RowSpec`/`LayoutSpec`.

## Goals / Non-Goals

**Goals:**
- Make a scaffolded-but-unfinished change visible for the whole ~6–7 minute
  authoring window, with the in-flight artifact identifiable at a glance.
- Ship A4 exactly: name cell + fixed-width right-anchored four-slot stage block,
  `┊`-separated, elbow-threaded.
- Guarantee that concurrently-authored changes stack with their stage columns
  vertically aligned, **by construction** (the stage block's width depends only
  on box width, never on name or stage) rather than by a per-row nudge.
- Colour the `┊` dividers on the border gradient, so they read as frame.
- Leave exactly one space between the `tasks` label and the right border.
- Zero change to the existing task-progress bar's rendering or its gather shape.
- Hand over cleanly: once `tasks.md` exists, the change is a task bar and nothing
  else.

**Non-Goals:**
- No narrow or medium rendering. The openspec section is wide-only today and
  stays wide-only (Decision 10).
- No timing, spinner, ETA, or elapsed display on the authoring row.
- No watching/inotify, no cache, no state file — presence is re-derived from the
  filesystem every tick, like every other gather source.
- No per-name spec gradient for the authoring row (Decision 6).
- No display of `.openspec.yaml` contents beyond what Decision 4 needs.
- No change to `openspec_bar` itself.

## Decisions

### 1. Detection: enumerate `openspec/changes/*` for dirs lacking `tasks.md`

`OpenSpec.from_cwd` gains a second pass, after the existing `rglob('tasks.md')`
loop, over `sorted((Path(root) / 'changes').iterdir())`:

- skip non-directories, names starting with `.`, and anything under `archive/`;
- skip any dir where `(d / 'tasks.md').is_file()` — that one is (or should be) a
  task bar and belongs to the existing pass;
- otherwise emit an `AuthoringChange`.

Two passes over disjoint sets, so a change can never appear in both collections.

*Alternative rejected:* deriving authoring state from a `tasks.md`-less
`rglob('.openspec.yaml')`. `.openspec.yaml` is a schema marker, not a lifecycle
marker; iterating `changes/` directly is one `iterdir` instead of a recursive
walk and matches the CLI's own directory contract.

**Edge case, deliberate:** the existing pass drops a `tasks.md` with zero
checkboxes (`if total == 0: continue`). Such a change is *also* excluded from the
authoring pass (it has a `tasks.md`), so it stays invisible exactly as today. No
regression, no new behaviour — noted so a later reader does not read it as an
oversight.

### 2. `AuthoringChange` shape

```python
class AuthoringChange:
    __slots__ = ('name', 'has_proposal', 'has_design', 'delta_count', 'delta_total')
```

- `name` — the change directory name (fixed at scaffold time, never renamed).
- `has_proposal` / `has_design` — `(d / 'proposal.md').is_file()` etc.
- `delta_count` — `len(list(d.glob('specs/*/spec.md')))`.
- `delta_total` — see Decision 4.

`tasks.md` is not a field: its absence is the entry condition for this list.

A slots class with `__eq__`/`__repr__` matches `OpenSpec`'s and `ToolCounts`'
existing style in this package; a `NamedTuple` would be equally acceptable but
would break the module's established convention.

### 3. Stage model: four slots, one active

The row has exactly four stage slots in fixed order —
`proposal`, `design`, `deltas`, `tasks` — each rendering one of three glyphs:

| state | glyph | colour |
|---|---|---|
| done | `GLYPH_TASK_DONE` | `r.safe` |
| active | `GLYPH_TASK_ACTIVE` | `r.yellow` |
| pending | `GLYPH_TASK_PENDING` | `r.LABEL` |

Per-slot rules:
- `proposal` / `design`: done iff the file exists.
- `deltas`: done iff `delta_count >= delta_total and delta_total > 0`;
  active iff `0 < delta_count < delta_total`.
- `tasks`: never done (its existence removes the row entirely) — pending or
  active only.

The **active** slot is the first non-done slot in order, except that `deltas`
already claims active when partially landed. Concretely: the first slot in
`(proposal, design, deltas, tasks)` that is not done is the active one; all
subsequent slots are pending. This makes "active" mean *the artifact currently
being drafted*, which is what the ~70–90 s inter-artifact gap makes observable.

### 4. `delta_total`: capability bullets in `proposal.md`

The number of spec deltas a change will produce is not knowable from the
scaffold. It **is** knowable from `proposal.md` once that lands: the Capabilities
section lists one bullet per capability, and each becomes one
`specs/<name>/spec.md`. `delta_total` is therefore the count of lines matching
`^\s*-\s+\`[a-z0-9-]+\`` under the `## Capabilities` heading of `proposal.md`
(both the New and Modified subsections, stopping at the next `## ` heading).

- Before `proposal.md` exists, `delta_total = 0` and the label renders
  `deltas ?/?` (see Decision 7's width rule).
- If `delta_count > delta_total` (a change authored more deltas than it
  declared), `delta_total` is clamped up to `delta_count`, so the slot can reach
  done and never displays a nonsensical `3/2`.

*Alternative rejected:* rendering just `deltas N` with no denominator. It loses
the "how much is left" signal that is the whole point of the deltas slot, and the
user's brief explicitly specifies the `N/M` form.

*Assumption flagged for confirmation:* this couples the deltas denominator to
proposal.md's Capabilities-bullet formatting. It is the repo's own house style
(see `openspec/changes/archive/**/proposal.md`), but it is a text convention, not
an enforced schema.

### 5. Elbow-threaded `┊` dividers — a deliberate break with the floating-divider convention

`layout.py:1324-1328` documents that the workflow two-column `┊` "floats free of
the frame — no `┬`/`┴` elbows". The authoring row does the opposite: **every**
`┊` gets an elbow on the row above and below. Rationale: the workflow divider
splits *content* into two reading columns, whereas here the dividers delimit
fixed structural cells whose alignment across stacked rows is the design's whole
premise; the elbows are what make that alignment legible. This is called out
explicitly so a later reader does not "fix" it to match the other convention.

There are **four** `┊` per row, and therefore four elbow columns: one between the
name cell and the stage block, plus three between the four stage cells.

### 6. Dividers take the border gradient, not a flat colour

Each `┊` is emitted as `f'{r.grad_at(col - 1, width, fill=fill)}{GLYPH_WF_DIVIDER}{RESET}'`,
where `col` is that divider's 1-indexed border column — the same expression and
the same `col - 1` off-by-one convention as `layout.py:479`. The consequence is a
**two-pass build**: the divider columns depend on the cell widths, and the
divider colours depend on the columns, so the row is laid out as plain
placeholders first, its columns computed, then the placeholders substituted with
their gradient-coloured glyphs. Computing colours inline while building would
require knowing each divider's final column before the string exists.

Because `grad_at` takes `fill`, `openspec_authoring_row` needs a `fill`
parameter, which `build_wide` already has in hand (it passes `fill=fill` to
`build_workflow_rows` at `layout.py:1319`).

*Alternative rejected:* `self.BORDER` flat colour. The user requirement is
explicit, and a flat divider between two gradient-coloured elbows would look
like a rendering bug.

### 7. Fixed-width stage block is the alignment mechanism

```python
AUTHORING_STAGE_LABEL_W = {'proposal': 8, 'design': 6, 'deltas': 10, 'tasks': 5}
```

Each label is truncated-then-`ljust`-ed to its width, so it is **constant
regardless of state**. `deltas` reserves 10 columns for `deltas N/M`, which fits
single-digit counts; counts above 9 are clamped to `9` and a `?` renders for an
unknown `delta_total`. **This constant-width property is load-bearing**: it is
the entire reason stacked rows align, and any future change to the label
templates must preserve it.

Cell = `glyph + ' ' + label`, so cell widths are 10 / 8 / 12 / 7 = 37. Dividers
are `' ┊ '` (3 columns) — 3 inter-stage + 1 name/stage = 12 — so the full-label
block plus its leading divider is 46 + 3 = **49 columns, invariant across name
and stage**. The name field is therefore `content_budget - 49`, and every row at
a given box width computes identical divider columns. The builder asserts this
(Decision 9).

### 8. Right gutter: content is built to `width - 4`, not `width - 3`

`border_line` pads with `pad = width - 3 - visible_width(content)`. The prototype
built content to exactly `width - 3` so `pad == 0` and `tasks` sat flush against
the border. The user requirement is one space of gutter, so the real
implementation targets `content_budget = width - 4`, leaving `pad == 1`. The
gutter comes from `border_line`'s own padding — the row does **not** append a
literal trailing space, which would be invisible to the width assertion and easy
to lose in a later edit.

### 9. Two-tier degrade, driven by the name-cell floor

```
name_field_w = (width - 4) - 3 - full_block_w      # 3 = the name/stage divider
if name_field_w >= AUTHORING_NAME_FLOOR (15):  full labels
else:                                          glyph-only stage cells
```

In glyph-only mode each cell is the bare glyph (width 1), so block + leading
divider is 4 + 12 = 16 columns and the name field becomes `width - 20`. Dividers
and elbows are retained in **both** tiers — only the labels shed.

The name cell absorbs all remaining slack: `ljust` to the field width when it
fits, else truncated to `field_w - 1` visible columns plus `ELLIPSIS`, measured
with `_visible_width`, never `len()`.

`AUTHORING_ROW_MIN_WIDTH` is the box width below which even the glyph-only tier
cannot give the name field a positive width; below it the authoring rows are
**dropped entirely** rather than rendered corrupt. Given the numbers above that
floor is well below the wide-layout threshold, so in practice it is a guard, not
a live branch — but it must exist, because the prototype's `max(eff_name_w, 1)`
clamp emits an over-wide row rather than surfacing the problem.

### 10. Placement: contiguous group above the task bars, wide only

Inside the existing openspec block (`layout.py:1334-1341`), authoring rows are
emitted **first**, then the task bars. Rationale: authoring rows are transient
and newsworthy; the task bars are the steady state. Elbow threading:

- the block's leading `RowSpec(sep_kind('separator'), ups=pending_ups + tail_ups, ...)`
  additionally gets `downs=stage_cols`;
- if task bars follow, a `RowSpec('separator_dim', ups=stage_cols)` is inserted
  between the two groups (this is a **new** separator; today the block has none
  between rows);
- if no task bars follow, `RowSpec('bottom_border', ups=stage_cols)` closes it.

The `('specs', 3)` caption stays on the leading separator and is unchanged. The
section header still appears when there are authoring rows but no task bars —
i.e. the block's presence condition becomes `openspec_bars or authoring_rows`.

Nothing is added to `build_narrow` / `build_medium`: they have no openspec
section to extend.

### 11. No new `render_layout` kind

The row is plain content plus border columns, so `RowSpec('content', content=line)`
suffices and `render_layout` needs no new branch. (Worth noting: `render_layout`
has no `else` branch, so an unhandled kind would silently render nothing — a
reason to avoid inventing one.)

### 12. `openspec_authoring_row` returns `(line, cols)`

Following the repo's established convention for section helpers that contribute
dividers (`model_section_compact`, `tokens_cost`), the helper returns the content
line together with its 1-indexed border columns, computed as `3 + off` from each
`┊`'s 0-indexed visible offset. `build_wide` threads the tuple into
`RowSpec.downs`/`.ups` wholesale.

### 13. No new glyph constants

`GLYPH_WF_DIVIDER`, `GLYPH_TASK_DONE`, `GLYPH_TASK_ACTIVE`, `GLYPH_TASK_PENDING`
and `ELLIPSIS` all already exist in `constants.py` with `ASCII_GLYPHS`,
`UNICODE_PUA` and (where needed) `GITHUB_ICON_OVERRIDE` entries. The PUA refactor
rule therefore imposes no new work — but the glyph-mode gate still applies,
because all four glyph substitutions must remain width-1 or the fixed-width
alignment invariant breaks.

## Risks / Trade-offs

- **[Constant-label-width invariant is silent if broken]** → A future edit that
  makes any stage label state-dependent (e.g. `deltas 10/12` overflowing its 10
  columns) breaks stacked-row alignment with no exception raised. Mitigated by
  a test asserting the rendered divider columns are identical across a matrix of
  names × stages, and by the two-digit clamp in Decision 7.
- **[`delta_total` depends on proposal.md prose]** → Decision 4 parses a markdown
  convention, not a schema. A proposal with unconventional Capabilities
  formatting yields `delta_total = 0` and a `deltas N/?` label. Degrades to a
  cosmetic inaccuracy, never a crash or a width change.
- **[New per-tick `iterdir` on `openspec/changes/`]** → One shallow directory
  listing plus up to ~4 `is_file()` / one `glob` per authoring change, and one
  small `read_text` of `proposal.md` per authoring change. Bounded by the number
  of *unfinished* changes (typically 0–2, since finished ones are archived). The
  common case — no authoring changes — costs exactly one `iterdir`. It is paid
  inside the same `@cached_property` as the existing walk, so narrow/medium
  renders that never read `changes` still pay nothing.
- **[Breaking the floating-divider convention]** → Decision 5 is a deliberate
  inconsistency with the workflow two-column divider. Mitigated by documenting
  the rationale in a code comment at the wiring site as well as here.
- **[Seam tests will pick up this repo's own changes dir]** →
  `_silence_dynamic` (`test/test_layout_seam.py:52-70`) already stubs
  `OpenSpec.from_cwd` to return `OpenSpec(changes=[])`; that stub must also
  produce an empty `authoring` list, or every seam test starts depending on
  whatever is mid-authoring in the working tree. This is the single most likely
  source of a flaky-test regression in this change.
- **[Demo fixtures]** → The `openspec` scenario shows only task bars today; a new
  authoring scenario (or an extension of the existing one) is needed for the
  visual gate to cover the row at all, plus re-goldening of `kitchen-sink`.
