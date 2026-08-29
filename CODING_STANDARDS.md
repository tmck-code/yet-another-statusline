# CODING_STANDARDS.md

How code is written in yet-another-statusline (YAS). Adapted from a sibling
repo's `CODING_STANDARDS.md` (audiovis) and grounded in this repo's own
existing conventions — `claude/yas/` module shapes, `test/` patterns, and the
invariants `CONTEXT.md` already documents.

## Precedence

1. `CLAUDE.md` (subagent-routing agreement — gates run via `verifier`, edits
   via `yas-editor`, discovery via `Explore`)
2. **This document**
3. `~/.claude/skills/python-style/SKILL.md`, `~/.claude/skills/pytest-style/SKILL.md`
4. `.claude/skills/tmck-code-statusline/SKILL.md` (renderer-specific
   invariants — PUA glyph hoisting, width math, elbow/border column rules)
5. Generic advice (Fowler's smell catalogue et al.)

Higher wins on conflict. `CONTEXT.md` is the source of truth for *displayed
terms* and *behavioural* rules (formatting, degrade/shed order, thresholds) —
this document does not re-derive those; it covers how the code that
implements them should be shaped.

## Types

**Frozen dataclasses for values that travel together; plain functions for
everything else.** `RowSpec` and `LayoutSpec` (`claude/yas/layout.py`) exist
because a row's `kind`, content, and elbow-threading data always move as a
unit — unpacking a tuple three call sites away is where bugs hide. `Theme`
(`claude/yas/themes.py`) and `Config` (`claude/yas/config.py`) are the same
shape: a bundle of resolved values with one construction path (`Config.load`,
`THEMES` registry) rather than ad hoc kwargs scattered at call sites.

Corollary: a domain scalar with real semantics (a soft limit, a token count,
a column width) gets a name via a constant or a typed field, not a bare
`int`/`float` threaded through several functions positionally.

Do not introduce a dataclass for a single-field wrapper, or generalise a
`RowSpec.kind` branch "for future use" with no current caller — see
*Deliberate deviations* below on when a bare helper is preferred instead.

## Docstrings

**One line by default.** Multi-line is reserved for stating an invariant the
code cannot make obvious on its own — the comment above `subagent_status`/
`subagent_marker_glyph` in `claude/yas/constants.py` is the shape to match:
it explains the four-state lifecycle model and *why* callers never need an
`isinstance`/`hasattr` guard, not what the next line does.

```python
def subagent_is_terminal(status: str) -> bool:
    """True for any non-running lifecycle state."""
    return status != 'running'
```

Test functions need no docstring when the name states the behaviour; add one
only when the name alone can't carry a genuinely non-obvious setup (see
*Tests* below).

## Comments

Default to none. A comment earns its place only when it documents a
non-obvious **why** — a value that would otherwise look arbitrary, an
invariant a future edit could silently break, or a hazard that bit someone
before. `claude/yas/layout.py`'s note on `dur_s` not being fixed-width (why
the code measures the rendered string instead of assuming a column count) is
the model: it heads off a *specific* silent regression, not a narration of
what the next line does. Never restate the code in prose, and never leave a
banner comment (`# ==== Section ====`) — module and function names carry
that job.

## Modules

**Small, single-purpose, and layered — imports flow one direction.** The
package is split into three bands and each stays inside its own lane:

- `claude/yas/info/` — the **gather** layer (`SessionView` and its
  `@cached_property` fields: `git`, `skills`, `subagents`, `workflows`,
  `tasks`, `tool_counts`, …). Pure reads of session/filesystem state, no
  render geometry, no disk writes.
- `claude/yas/render/` — renderer building blocks (`GradientEngine`,
  `BorderRenderer`, `text._visible_width`/`_middle_ellipsis`, `metrics`,
  `tasks_view`). Pure computation over already-gathered data.
- `claude/yas/renderer.py`, `layout.py`, `app.py` — the **present** layer:
  `Renderer` section helpers, `RowSpec`/`LayoutSpec`/`build_*`/
  `render_layout`, and the `render`/`main` entry points that tie gather +
  present together and own the one place per-render side effects belong
  (`record_tick`).

`info/` must never import `renderer`; `render/` building blocks must never
import `layout`/`app`. If a change needs to reach upward across a layer, it
belongs in the layer above, not as a new import edge below. A module edited
for several unrelated reasons (e.g. `constants.py` growing a new *behaviour*
rather than a new *constant*) should be split before it grows further.

## Style

From `python-style` — the authoritative list is in that skill; the
load-bearing points for this repo:

- Standard library first (`tomli` is the one justified exception, gated to
  `python_version < '3.11'` — see `pyproject.toml`).
- Single quotes throughout, including single-line docstrings.
- Nesting ≤2 levels, 3 hard maximum — early `return`/`continue` to flatten.
- No `Any`, no `cast(...)` without a justifying comment (`mypy` runs
  `strict = true`, `disallow_untyped_defs = true` on `claude/`).
- `from __future__ import annotations` for self-referential hints.
- No banner comments.
- Named constants for glyphs and colours, never inline escapes —
  `claude/yas/constants.py` is the single home for every ANSI colour and PUA
  glyph constant (`GLYPH_MODEL_LIGHT`, `ICON_LIMIT_5H`, `CLR_BORDER_OFF`, …).
  A raw Nerd Font PUA codepoint (U+E000–U+F8FF, U+F0000–U+FFFFD) must never
  appear inline in `renderer.py`/`layout.py` — see the `tmck-code-statusline`
  skill's PUA-hoist rule for the mechanics.
- Column/width math never uses `len()` — use `_visible_width` (or its
  siblings in `claude/yas/render/text.py`). `len()` on a string containing
  ANSI escapes or a PUA glyph silently returns the wrong number of columns.
- Imports at module top, no lazy/conditional imports.

### Avoid repeated switches — prefer dict-based dispatch

When the same `if/elif` chain over a small closed set of string/enum values
recurs (or is likely to recur at a second call site), extract it to a
dict-lookup helper instead of re-writing the chain inline. The in-repo model
is `claude/yas/constants.py`'s subagent-lifecycle trio:

```python
def subagent_marker_glyph(status: str) -> str:
    return {
        'completed': GLYPH_SUBAGENT_DONE,
        'killed':    GLYPH_SUBAGENT_ENDED,
        'stopped':   GLYPH_SUBAGENT_ENDED,
        'failed':    GLYPH_SUBAGENT_FAILED,
    }.get(status, '')
```

`subagent_status`/`subagent_is_terminal`/`subagent_marker_glyph` together
give every caller (renderer, layout, tests) one shared, testable definition
of the lifecycle instead of each re-deriving it with its own `if status ==
'killed' or status == 'stopped'` chain. Reach for this shape whenever a
status/kind/mode string is branched on in more than one place, or when a new
value being added means auditing every scattered `if/elif` for a missed
branch — a `.get(key, default)` lookup can't silently omit a case the way a
copy-pasted `elif` chain can.

## Tests

Corroborated by the actual shape of `test/` (function-style, not
class-style — unlike `pytest-style`'s generic `Test<Subject>` class
guidance, this repo's ~965 test functions across `test/test_*.py` files use
bare `def test_...():`; follow the existing file's shape rather than
introducing class wrappers):

- Names describe behaviour (`test_model_key_ignores_bracket_suffix`,
  `test_gradient_rgb_clamps_above_one`). No task IDs or spec numbers in the
  name or body.
- Keep the setup → run → assert shape blank-line separated where a test has
  enough moving parts to need it; trivial one-liners (`assert f(x) == y`)
  don't need the separation forced on them.
- **Compare whole objects/tuples** where the function returns one
  (`assert _r.gradient_rgb(0.0) == (40, 210, 80)`), not per-field asserts.
- Shared string/ANSI helpers live in `test/helper.py` (`strip_ansi`); shared
  fixtures live in `test/conftest.py` — extend it, don't add a second
  conftest or duplicate a fixture inline in a test module.
- **Do not mock real rendering/layout logic.** `test/conftest.py` shells out
  to the real `claude/statusline_command.py` and monkeypatches only
  environment-shaped things (`HOME`, clock, config env vars) — replacing a
  renderer/layout function with a stub tests the harness, not the code.
- New behaviour gets a new or updated test in the same change — see the
  post-edit gate in `CLAUDE.md`/the `tmck-code-statusline` skill.
- Visual/width regressions are frequently invisible to `pytest` (a dropped
  PUA glyph or an off-by-one column doesn't always fail an assertion) — the
  `make demo`/`make demo/img` gate exists precisely to catch what a unit
  test can't; don't treat a green `pytest` run alone as sufficient for
  renderer/layout/glyph changes.

## Ops

**The Makefile is the front door.** `make test` (→ `uv run pytest -q`),
`make demo` / `make demo/img`, and `uv run ruff check` are the three gates —
run them via the `verifier` subagent per `CLAUDE.md`, never inline on the
main thread. There is no Docker requirement in this repo; `uv` runs directly
against the project venv.

## Project rules

Cross-references, not restatements — read `CLAUDE.md` and `CONTEXT.md` for
the detail:

- **Route through subagents.** Renderer/layout/glyph edits go to
  `yas-editor`; gates go to `verifier`; multi-file discovery goes to
  `Explore`. The main thread decides *what* and *which agent*, not *how*.
- **CONTEXT.md is the glossary of displayed terms and behaviour rules** —
  e.g. exact degrade/shed order under width pressure, the **Compaction-Risk
  Zone** thresholds, the **Glyph Mode** translation tables. When a rule and a
  displayed term already have a canonical name there, use it — don't
  reintroduce a synonym.
- **PUA glyph hoist rule.** Before editing a line that contains a raw Nerd
  Font PUA glyph, hoist it to a named constant in `constants.py` first. Raw
  glyphs are dropped through some editing round-trips and make string
  matching fail with a misleading "not found" error — see the
  `tmck-code-statusline` skill for the exact mechanics and the Bash/`python3`
  heredoc fallback when a direct edit genuinely can't be done first.
- **Width math never uses `len()`.** Always `_visible_width` (`render/text.py`).
- **No per-layout special cases inside `render_layout`.** A new layout
  variant threads through `RowSpec`/`LayoutSpec`, not an `if` branch keyed on
  a layout name inside the generic renderer.

## Deliberate deviations from received wisdom

These are settled rulings for this repo. Do not re-raise them in review.

**One-line delegating wrappers are an accepted idiom, not "Middle Man".** A
named wrapper over a composed call (e.g. a small `Renderer` helper that just
formats and delegates to `fmt_tok`/`_visible_width`) buys a readable call
site at the section-renderer boundary. Keep it.

**A helper with one caller is fine, not "Speculative Generality."** The
smell applies only to code with **zero** callers — a dead `Config` knob, an
unused constant — not to a small helper that exists because it names a
concept clearly, even if only `renderer.py` calls it today.

**`@dataclass` is banned in `claude/yas/**`.** Its cost is class-definition
time paid at import, and the statusline is a cold-start CLI where import time
is runtime — 16 conversions measured 1.13-1.18x slower. Use hand-written
`__slots__` classes and accept the extra lines. Full measurements and
reasoning in `KNOWN_ISSUES.md`.

**`else` after `return` is accepted** where the symmetry between branches
reads better than dropping the `else` — not a review finding on its own.

## Known conflicts

None currently flagged. If a future find contradicts a rule above, resolve
it here explicitly (with the losing convention marked "legacy, not a
precedent") rather than leaving both readings live.
