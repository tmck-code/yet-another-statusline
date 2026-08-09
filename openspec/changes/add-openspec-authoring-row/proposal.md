## Why

While an OpenSpec change is being *authored* — the ~6–7 minutes between
`openspec new change <name>` and the moment `tasks.md` lands — the statusline
shows nothing at all. `OpenSpec.from_cwd` discovers changes by globbing
`tasks.md`, so a scaffolded change is structurally invisible until the very last
artifact of the authoring pass exists. The user watching a `spec-author` subagent
work has no signal that anything is happening, and no signal about *which* of the
four artifacts is in flight. Since the artifact order is fixed and knowable
(proposal → design → 1–N spec deltas → tasks), a four-slot staged checklist can
show exactly that, in the box the change will later occupy anyway.

## What Changes

- **New gather source**: `OpenSpec.from_cwd` additionally enumerates
  `openspec/changes/*/` directories that have **no `tasks.md`**, and reports each
  as an *authoring* change with its per-artifact presence state
  (proposal.md, design.md, count of `specs/**/spec.md`, tasks.md absent).
- **BREAKING (internal):** `OpenSpec` grows a second collection,
  `OpenSpec.authoring: list[AuthoringChange]`, alongside the existing
  `changes: list[tuple[str, int, int]]`. `SessionView` gains a matching
  `authoring_changes` cached property. The `changes` list and its shape are
  unchanged, so every existing task-bar call site keeps working.
- **New renderer section** `Renderer.openspec_authoring_row(...)` rendering the
  validated **A4** design: a name cell, then a fixed-width, right-anchored block
  of four stage cells, all separated by `GLYPH_WF_DIVIDER` (`┊`):
  `<name cell> ┊ <glyph>proposal ┊ <glyph>design ┊ <glyph>deltas N/M ┊ <glyph>tasks`.
  It returns `(line, cols)` so the builder can thread real `┬`/`┴` elbows.
- **Gradient-coloured in-row dividers**: each `┊` is painted with
  `r.grad_at(col - 1, width, fill=fill)` so the dividers sit on the same border
  gradient as the frame — not the flat/dim style the workflow two-column divider
  uses. This is a deliberate departure from the existing "dashed divider floats
  free of the frame" convention (`layout.py:1324-1328`), because here the
  dividers *are* frame structure: they carry elbows.
- **One-space right gutter**: the row's content is built to exactly `width - 4`
  visible columns, so `border_line`'s own padding leaves exactly one space
  between the `tasks` label and the right border.
- **Layout wiring** in `build_wide`: authoring rows render as a contiguous group
  inside the existing openspec box, **above** the task bars, with the stage
  divider columns threaded as `downs` on the separator above and `ups` on the
  separator (or bottom border) below.
- **Two-tier degrade**: the name cell absorbs all slack (pad → truncate with
  `ELLIPSIS` → floor at 15 visible columns); only once the floor no longer leaves
  room do the stage cells shed their labels and render glyph-only, keeping the
  dividers and elbows.
- **Handover**: the moment `tasks.md` appears, the change leaves `authoring` and
  enters `changes`, so the existing task-progress bar takes over with no
  special-casing on either side.
- **No new glyphs.** `GLYPH_WF_DIVIDER`, `GLYPH_TASK_DONE`, `GLYPH_TASK_ACTIVE`,
  `GLYPH_TASK_PENDING` and `ELLIPSIS` already exist and already have
  `ASCII_GLYPHS` / `UNICODE_PUA` entries.

## Capabilities

### New Capabilities
- `openspec-authoring-row`: the authoring-stage row — which changes qualify, the
  four stage slots and their done/active/pending semantics, the fixed-width
  right-anchored stage block and its cross-row alignment guarantee, the
  gradient-coloured `┊` dividers with real elbows, the one-space right gutter,
  the name-cell slack/truncation/floor rules, the glyph-only degrade, the
  wide-only regime, and the handover to the task bar when `tasks.md` lands.

### Modified Capabilities
- `statusline-info`: the openspec gather field additionally enumerates
  scaffolded-but-unfinished changes and exposes their per-artifact state, while
  keeping the existing lazy, pure-read, render-independent contract.
- `openspec-bar-colour`: the name-derived, render-stable gradient selection rule
  is scoped explicitly to the task-progress bar; the authoring row uses the
  frame's border gradient for its dividers instead of a per-name spec gradient.

## Impact

- `claude/yas/info/openspec.py` — new `AuthoringChange` value, new enumeration
  pass over `openspec/changes/*`, `OpenSpec.authoring`, `__eq__`/`__repr__`.
- `claude/yas/info/__init__.py` — `SessionView.authoring_changes` cached
  property; `changes` docstring notes the split.
- `claude/yas/renderer.py` — new `openspec_authoring_row` section helper.
- `claude/yas/layout.py` — `build_wide` builds the authoring rows and threads
  their divider columns through the openspec block's separators.
- `claude/yas/constants.py` — `AUTHORING_STAGE_LABEL_W`, `AUTHORING_NAME_FLOOR`,
  `AUTHORING_ROW_MIN_WIDTH` (no new glyphs).
- `test/test_openspec_bar.py`, `test/test_layout_seam.py`, new
  `test/test_openspec_authoring.py` — rendering, column-alignment, degrade,
  gather and laziness tests. `_silence_dynamic` must also neutralise the new
  enumeration or the seam tests pick up this repo's own `openspec/changes/`.
- `demo/text/*.txt` — the `openspec` and `kitchen-sink` scenarios need an
  authoring fixture and re-goldening.
- `demo/prototype_openspec_authoring.py` — deleted once this ships (it is
  explicitly marked throwaway).
- `CONTEXT.md` — glossary entries for Authoring Stage and the four stage slots.
