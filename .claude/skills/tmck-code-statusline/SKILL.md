---
name: tmck-code-statusline
description: Edit the Claude Code statusline renderer safely. Use when touching claude/statusline-command.py, claude/statusline/*.py, claude/statusline-command.sh, or related tests. Covers the layered renderer (GradientEngine / BorderRenderer / Renderer), the LayoutSpec/RowSpec layout pipeline, Nerd Font PUA glyph hazards, border/elbow column math, and the demo-based visual check.

---

# Statusline

The statusline renderer is a single-pass terminal painter with hand-tuned column math. Most bugs here are silent — wrong by one column, invisible icon, dropped byte through an Edit round-trip. This skill exists to make those bugs loud.

## Architecture map (post-refactor)

`claude/statusline-command.py` is layered:

- **`GradientEngine`** (~L968): pure colour/sparkline math. `gradient_rgb`, `gradient_color`, `grad_at`, `gradient_bar`, `sparkline`. No I/O, no terminal state.
- **`BorderRenderer`** (~L1045): consumes a `GradientEngine`. Owns `border_top`, `border_bottom`, `border_separator`, `border_separator_dim`, `border_line`. All elbow / pill / fill math lives here.
- **`Renderer`** (~L1147): composes the two (`self.gradient`, `self.border`) and adds every section helper (`path_git`, `path_git_compact`, `model_section`, `model_section_compact`, `path_model_row`, `plugins_skills`, `tokens_cost`, `context_line`, `context_line_compact`, `openspec_bar`, `helper`, the colour pickers, etc.). Keeps thin delegators (`gradient_color`, `border_top`, …) for backward-compat callers and tests.
- **`Pill`** (~L113, `@dataclass`): the model-effort coloured pill. `active`, `gradient_fg`, `border_char(col, edge)`, `border_fg(col)`. Border helpers accept a `pill: Pill | None` and a `pill_edge: 'top' | 'bottom'`.
- **`TokenAccounting`** (~L158): static `rates_for`, `session_cost`, `day_cost`. Don't inline rate math elsewhere.
- **Layout pipeline** (~L1633–1844): `RowSpec` (kind ∈ {`top_border`, `bottom_border`, `separator`, `separator_dim`, `content`} + content/`ups`/`downs`/`bg_lead`/`bg_trail`/`pill`/`pill_edge`/`pill_flush`) is built into a `LayoutSpec` by one of `build_narrow` / `build_medium` / `build_wide`, then `render_layout(spec, r)` walks rows and dispatches to the matching `Renderer`/`BorderRenderer` method.

**Where to make a change:**

- Section content (a row's text) → the corresponding `Renderer` helper.
- Row order, conditional rows, elbow threading → the relevant `build_*` function. Never edit `render_layout` to special-case a layout; thread it through `RowSpec` instead.
- New border style → `BorderRenderer`, then a new `RowSpec.kind` branch in `render_layout`, then use it from a builder.
- New gradient/sparkline maths → `GradientEngine`. Add a `Renderer` delegator only if existing tests/callers expect it on `Renderer`.

## Pre-edit checklist

Run all four before editing:

1. **Read `CONTEXT.md`** at repo root. The terms Billed Input, Cache Read, Output, Day Total, Context Window Size, Compaction-Risk Zone, Five-Hour Limit, Seven-Day Limit are canonical — don't rename or alias them in code without a paired update.
2. **Catalogue PUA glyphs on touched lines.** Run:
   ```bash
   python3 -c "
   import sys
   for ln, line in enumerate(open(sys.argv[1]), 1):
       for c in line:
           cp = ord(c)
           if 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0xFFFFD:
               print(f'{sys.argv[1]}:{ln}  U+{cp:05X}  {c!r}')
   " claude/statusline-command.py
   ```
   Any hit on a line you plan to Edit triggers the **PUA refactor rule** below.
3. **Baseline tests**: `uv run pytest -q`. Note pass count.
4. **Baseline demo**: `make statusline/test` (or `uv run python claude/statusline/demo.py`). It animates 60 frames in place via cursor escapes; eyeball the final frame and the elbow alignment as it crosses layout thresholds (narrow → medium → wide on $COLUMNS). For a static snapshot when piping is needed, render one frame directly: `COLUMNS=160 uv run python claude/statusline-command.py < claude/statusline/session-info-example.json` (no transcript-derived rows; enough for border math).

## PUA refactor rule (mandatory before editing)

Nerd Font icons in this repo live in the Unicode Private Use Area (U+E000–U+F8FF and U+F0000–U+FFFFD). Literal PUA glyphs in source are invisible in many editors, render as `□` in others, and **get dropped through chat/agent round-trips** — which makes `Edit.old_string` matching fail with a stale-looking "string to replace not found" error.

If a line you need to Edit contains a raw PUA glyph, **hoist the glyph to a named module-level constant first**, then Edit. No exceptions.

Convention (matches the existing constants near L95–L101 of `statusline-command.py`):

```python
# Nerd Font Private Use Area glyphs. Encoded as escapes so Edit, diff, and
# chat round-trips never lose the bytes. Render only in a Nerd-Font-capable
# terminal.
ICON_COST      = '\uefc8'     # nf-md currency-usd       (cost row)
ICON_TOK_RATE  = '\U000f18a7' # nf-md gauge              (t/m rate label)
GLYPH_MODEL    = '\U000f08b9' # nf-md monitor-dashboard  (model row)
GLYPH_THINKING = '\U000f1a53' # nf-md brain              (thinking indicator)
```

Reference the constant in f-strings: `f'{model_clr}{GLYPH_MODEL}  {model_name}...'`. Note that names like `Renderer.ICON_PATH` already exist on the `Renderer` class but hold a *colour code*, not a glyph — don't reuse that namespace for glyphs. New glyph constants go at module scope alongside `ICON_COST`/`GLYPH_MODEL`.

Runtime cost is **zero** — `'\uefc8'` (in source) and the literal glyph compile to the identical `str` object; CPython interns and the `.pyc` cache eliminates parse cost after first load.

### Fallback when refactor isn't feasible mid-task

If the line has a PUA glyph and you genuinely can't refactor first (e.g., user is mid-edit and asked for one surgical change), use a Bash heredoc with `python3` that reads, `str.replace`s, and writes. Python preserves the bytes exactly:

```bash
python3 << 'PY'
path = 'claude/statusline-command.py'
with open(path) as f:
    s = f.read()
old = "...exact old text with raw glyph copied through Read...\n"
new = "...replacement...\n"
assert old in s, 'old not found'
with open(path, 'w') as f:
    f.write(s.replace(old, new, 1))
PY
```

This works because `Read` preserves the bytes when it loads them into your context, even when subsequent `Edit` calls can't transmit them through `old_string`.

## Rendering invariants (silent-bug cheat-sheet)

These are the things pytest won't catch — get them wrong and the box draws crooked.

### Width math

- **Never** use `len()` for column math. Use `_visible_width` (L153) — it strips ANSI escapes via `_ANSI_RE` (L31) and counts wide chars (BMP emoji `0x1F300–0x1FAFF`) as 2.
- Nerd Font PUA chars count as width 1. Correct in a Nerd-Font terminal; would be wrong elsewhere, but elsewhere isn't supported.

### Column indexing on borders

- `border_top(width, session_id='', downs=..., fill=..., pill=...)`, `border_separator(width, ups=...)`, `border_separator_dim(width, downs=..., ups=..., pill=..., pill_edge=...)`, `border_bottom(width, ups=...)` take **1-indexed visual positions** of the inline `│` they should attach an elbow to. Live on `BorderRenderer`; `Renderer` has matching delegators.
- `border_line(content, width, fill=..., bg_lead='', bg_trail='', pill_flush=False)` wraps content as `│ <content>...│`. Content starts at visual column 2, which is **col-form 3** (1-indexed).
- A `Pill` passed to `border_top` / `border_separator_dim` paints itself across `[pill.start, pill.end]` using `border_char(col, edge)` instead of the default top/separator glyph. `pill_edge='top'` is used when the pill sits *below* the separator (rare; the narrow/medium → wide path uses it when there's no path-row above the model row).

### vsep convention

The vertical divider inside a content row is the 5-char string `'  │  '` (two spaces, pipe, two spaces). The `│` sits at vsep-index 2.

```python
vsep = f'  {self.BORDER}│{self.R}  '   # visible width 5; │ at offset 2
```

### Section helpers that participate in dividers return `(line, div_offset)`

When a section contributes a `│` that should grow elbows on the surrounding borders, the helper returns `(line, div_offset)` where `div_offset` is the **0-indexed visible position of the `│` inside `line`**. Examples: `path_model_row`, `model_section`, `model_section_compact`, `tokens_cost` (which returns `(lines, vsep_cols)`).

Caller (a `build_*` function) converts to a border col and threads it into `RowSpec.downs` / `RowSpec.ups`:

```python
# Standalone row:
model_div_col = 3 + model_div_offset

# Inside a combined row whose own divider sits at top_div_col:
model_div_col = top_div_col + 3 + model_div_offset

rows = [
    RowSpec('top_border',     downs=(top_div_col, model_div_col)),
    RowSpec('content',        content=combined_line, bg_trail=bg_trail),
    RowSpec('separator_dim',  ups=(top_div_col, model_div_col)),
    ...
]
```

Every `┬` in a top border must line up with a `│` in the row beneath it and a `┴` in the separator below — `ups`/`downs` are how you make that happen.

### Gradient

`grad_at(i, width, fill=...)` returns the ANSI for column `i` of the rainbow border. Don't reorder the `parts` list when extending border helpers — the gradient is positional.

## Layout-spec rules

- A `build_*` function returns a fully-populated `LayoutSpec`. Don't push rendering side effects into it; only build `RowSpec`s.
- New row types need: a new `kind` string, a branch in `render_layout` (~L1831), and a `BorderRenderer` method (if it draws a border) or a `Renderer` section helper (if it's content).
- Conditional rows: append to a local `rows: list[RowSpec]` and assign `spec.rows = rows` at the end. See `build_wide` for the canonical pattern with optional `plugins_line` and `openspec_bars`.
- When a row drops out (e.g., no plugins), the surrounding `ups`/`downs` need to be re-threaded — `build_wide` carries a `next_ups` local for this. Don't try to "fix it up" inside `render_layout`.
- Pill threading: when the pill is active, the row immediately under the top border uses `pill_flush=True` and an empty `bg_lead`; the surrounding `top_border` / `separator_dim` receive the same `Pill` object. When the pill is *inactive*, you fall back to `bg_lead`/`bg_trail` and elbow `ups`/`downs`.

## Post-edit checklist

1. **`uv run pytest -q`** — must be green. The pass count should match the baseline plus any tests you added.
2. **`make statusline/test`** — eyeball the animation:
   - Every `┬` in a top border lines up with a `│` in the row beneath it and a `┴` in the separator below.
   - Pill colours flow continuously across the top, sides, and bottom of the model row.
   - Resize the terminal narrower/wider during the run to verify the narrow ↔ medium ↔ wide thresholds.
3. **Tests** — any behaviour change needs a test added or updated. Use the `strip_ansi` helper from `test/conftest.py` (which imports the script as `statusline_command`). Width-sensitive assertions go through `_visible_width`. Put new tests in the file that matches the layer touched: `test_gradient_math.py`, `test_borders.py`, `test_model_section.py`, `test_context_line.py`, `test_openspec_bar.py`, `test_tokens_cost.py`, etc.
4. **`CONTEXT.md`** — if any displayed term changed (label, glyph meaning, what a number represents), update the glossary in the same change.

## Sibling skills

`python-style` and `pytest-style` apply as usual when touching `.py` files. This skill adds the statusline-specific rules on top.
