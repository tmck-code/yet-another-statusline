## Why

The cwd/path section degrades under width pressure by *middle-ellipsizing* the
path (and, at the extreme, the branch too). Chopping the middle out of an
already-abbreviated path (`~/d/yet-another-statusline`) is hard to read and the
ladder is more elaborate than it needs to be. The path should be treated as a
whole: included when it fits, omitted when it doesn't — never partially mangled.

## What Changes

- Replace `fit_path`'s middle-ellipsis fallback stages with a whole include/omit
  ladder for the cwd path.
- New degradation order: full (path + branch + commit + dirty) → drop commit →
  drop dirty → **drop the cwd path entirely** (branch retained) → **drop the
  branch** (presence glyph only).
- Priority is branch over cwd: the branch survives longer than the path.
- No middle-ellipsis is applied to the path at any stage; the glyph-only final
  state is overflow-safe (cannot break the box border math).

## Capabilities

### New Capabilities
- `path-display`: the cwd/branch section's width-degradation behavior —
  whole-unit include/omit with a fixed drop priority and an overflow-safe
  terminal state.

### Modified Capabilities
<!-- none -->

## Impact

- `claude/yas/renderer.py` — `Renderer.fit_path` (degradation ladder; removal of
  the middle-ellipsis tail). `path_git` / `path_git_compact` unchanged in shape.
- Both call sites in `claude/yas/layout.py` (narrow `compact_only=True` and wide
  `compact_only=False`) inherit the new ladder.
- Tests: a `test/` module covering `fit_path` at decreasing widths.
- No change to border/elbow math; the section's visible width still governed by
  `_visible_width`.
