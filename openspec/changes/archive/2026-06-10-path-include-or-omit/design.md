## Context

`Renderer.fit_path` (`claude/yas/renderer.py:340`) currently degrades through
six stages: full `path_git`; drop commit; drop commit+dirty; `path_git_compact`;
compact with **middle-ellipsis on `short_pwd`**; compact with **middle-ellipsis
on both `short_pwd` and the branch**. `short_pwd` (`session.py:278`) already
collapses parent segments to initials and keeps the basename full.

Both layout call sites use it: `build_narrow` with `compact_only=True`
(line 184) and the wide builder with `compact_only=False` (line 302).

## Goals / Non-Goals

**Goals:**
- Treat the cwd path as a whole unit — included in full or omitted, never
  middle-ellipsized.
- Make the degradation ladder shorter and predictable, with branch outliving
  path.
- Keep an overflow-safe terminal state so the box border never breaks.

**Non-Goals:**
- Changing `short_pwd`'s initial-collapsing scheme.
- Changing border/elbow math or the section's position in the row.
- Ellipsizing the branch as a path-ladder step (branch is whole-or-omitted too;
  glyph-only is the floor).

## Decisions

- **New ladder** in `fit_path`, first candidate that fits via `_visible_width`:
  1. `path_git(...)` — path + branch + commit + dirty
  2. `path_git(..., show_commit=False)`
  3. `path_git(..., show_commit=False, show_dirty=False)`
  4. **path omitted, branch kept** — a branch-only form (glyph + arrow + branch)
  5. **glyph only** — presence indicator, guaranteed to fit
- **Remove** the two middle-ellipsis tail stages entirely.
- **Branch-only form:** introduce a small render path that emits the git glyph +
  branch without the cwd segment (either a new helper or a flag on the existing
  path renderer). Reuses existing colour constants; no new glyph.
- **`compact_only=True`:** the narrow builder skips the full `path_git` stages
  and enters at the compact/branch-only rungs, preserving today's narrow entry
  behavior while gaining the whole-omit semantics.
- **Glyph-only floor:** 1–2 visible columns; always ≤ target width, so the
  terminal state can never overflow.

## Risks / Trade-offs

- **More abrupt transitions:** at medium widths a path that used to show as
  `~/d/long…name` now disappears entirely once it stops fitting. This is the
  intended behavior (legibility over partial detail) and is the explicit ask.
- **Branch-only helper surface:** adds one rendering path; mitigated by keeping
  it a thin variant of the existing path renderer rather than a parallel
  implementation.
- **Test coverage:** width-threshold transitions must be asserted via
  `_visible_width` at several target widths to lock the new ladder and prove the
  glyph-only floor never overflows.
