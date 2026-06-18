---
name: tmck-code-statusline
description: Edit the Claude Code statusline renderer safely. Use when touching claude/yas/**/*.py (the yas package), claude/statusline_command.py (the entry shim), claude/mon.py, or related tests under test/. Covers the layered renderer (GradientEngine / BorderRenderer / Renderer), the SessionView gather seam (yas/info/__init__.py), the LayoutSpec/RowSpec layout pipeline, record_tick/TickRecord, Nerd Font PUA glyph hazards, border/elbow column math, and the demo-based visual check.

---

# Statusline

The statusline renderer is a single-pass terminal painter with hand-tuned column math. Most bugs here are silent — wrong by one column, invisible icon, dropped byte through an Edit round-trip. This skill exists to make those bugs loud.

## Architecture map (post-package-split)

`claude/statusline_command.py` is a 4-line shim: `from yas.app import main`. The real code is the **`yas`** package under `claude/yas/`, split so each module compiles to a cached `.pyc` (the split exists for startup speed). Tests, the shim, and `mon` resolve it via `pythonpath = ["claude"]` (see `pyproject.toml`), so imports are `yas.<module>` / `yas.info.<module>` / `yas.render.<module>`.

The package is laid out in three layers:

- **`claude/yas/`** (top level) — `app.py`, `layout.py`, `renderer.py`, `session.py`, `config.py`, `constants.py`, `themes.py`, `tokens.py`.
- **`claude/yas/info/`** — the data-source / gather layer: `__init__.py` (the `SessionView` seam), `git.py`, `openspec.py`, `skills.py`, `subagents.py`, `tasks.py`, `transcript.py`.
- **`claude/yas/render/`** — the pure painting/maths layer: `gradient.py`, `borders.py`, `pill.py`, `text.py`, `metrics.py`, `tasks_view.py`.

Entry points live in **`app.py`**:
- `render(session_info, width, *, bg_shift, theme) -> str` — the public callable (also what `mon.py` imports). Constructs `SessionInfo`, `Config`, `SessionView`, picks a `build_*` by width (wide also calls `record_tick`), renders the `LayoutSpec`.
- `record_tick(session, usage) -> TickRecord` — the per-render write boundary. Runs `TokenLog.update` / `TokenRate.update` / `compute_day_cost` and bundles results into a `TickRecord` (the dataclass itself lives in `tokens.py`). Called by `render` before `build_wide`; receives `view.transcript_usage` (cached) so the transcript is scanned only once.
- `main()` — stdin → JSON → `render`, plus forces UTF-8 stdout and writes the per-session payload to `~/.claude/statusline-output/statusline.<session_id>.json` for the observer.
- `resolve_theme(cli_name)` — CLI → `YAS_THEME` → … → `CLAUDE_DARK`.

The renderer is layered across three modules (`render/gradient.py`, `render/borders.py`, top-level `renderer.py`):

- **`render/gradient.py`** — pure colour/sparkline math. Module-level `rainbow_step`, `rainbow_at`, `rainbow_color`, `model_key`, `_scale`, `paint_bg_span`, `pill_gradient_fg`, plus the **`GradientEngine`** class (`gradient_rgb`, `gradient_color`, `grad_at`, `gradient_bar`, `spark_*`, `sparkline`). No I/O, no terminal state.
- **`render/borders.py`** — **`BorderRenderer`** consumes a `GradientEngine`. Owns `border_top`, `border_bottom`, `border_separator`, `border_separator_dim`, `border_line`, `_dim_for_col`. All elbow / pill / fill / `right_pill` math lives here.
- **`renderer.py`** (top level) — **`Renderer`** composes the two (`self.gradient`, `self.border`) and adds every section helper (`path_git`, `path_git_compact`, `fit_path`, `model_section_compact`, `model_right_section`, `model_right_section_compact`, `plugins_skills`, `subagent_activity`, `subagent_row`, `task_row`, `tokens_cost`, `context_bar`, `context_line`, `context_line_compact`, `openspec_bar`, `spec_gradient_bar`, `burndown_trend`, `helper`, the colour pickers, `vsep_block`, …). Keeps thin delegators (`gradient_color`, `border_top`, …) for backward-compat callers and tests. Module-level `LEVEL_PCT` and `TOOL_ARG_KEY` dicts live here too.

Supporting modules:

- **`render/pill.py`** — `Pill` (`@dataclass`): the model-effort coloured pill. `active`, `gradient_fg(col)`, `border_char(col, edge)`, `border_fg(col)`. Border helpers accept `pill: Pill | None` and `pill_edge: 'top' | 'bottom'`.
- **`render/text.py`** — width/format primitives: `_visible_width`, `_is_wide`, `terminal_width`, `_middle_ellipsis`, `fmt_tok`, `fmt_dur`, `sparkline_width`.
- **`render/metrics.py`** — `burndown_delta`, `subagent_avg_tpm`, `subagent_share`.
- **`render/tasks_view.py`** — task-row geometry: `WindowSlice`, `fmt_duration`, `total_elapsed`, `select_window` (the windowing/elapsed maths behind `Renderer.task_row`).
- **`constants.py`** — width thresholds (`MIN_WIDTH=40`, `NARROW_WIDTH=55`, `MEDIUM_WIDTH=80`, `DEFAULT_MAX_WIDTH=140`), `_ANSI_RE`, `BarChars`, all `CLR_*` colour codes, `RESET`/`BOLD`/`ITALIC`, the five-hour / seven-day limit constants, `RAINBOW_PALETTE`, `CLAUDE_DIR`, and **every Nerd Font PUA glyph constant** (`ICON_COST`, `GLYPH_MODEL`, `SPARK_*`, `PILL_*`, …). This is the hoist target for the PUA rule below.
- **`tokens.py`** — `TokenAccounting` (static `rates_for`, `session_cost`, `day_cost`), `TokenLog` and `TokenRate` (the on-disk t/m rate history), the `TickRecord` dataclass, and module-level `compute_session_cost` / `compute_day_cost`. Don't inline rate math elsewhere.
- **`session.py`** — `SessionInfo.from_dict` and every typed view of the stdin payload (`Model`, `OutputStyle`, `Effort`, `Thinking`, `Workspace`, `Cost`, `ContextWindow`, `RateLimits`, `RateBucket`, `CurrentUsage`, …) plus `_as_int/_as_float/_as_str` coercers.
- **`config.py`** — `Config` (frozen dataclass): merges `yas.toml`, env vars, and argv; `soft_limit_for(model_id, display_name)`.
- **`info/git.py`** / **`info/openspec.py`** / **`info/skills.py`** / **`info/subagents.py`** / **`info/tasks.py`** / **`info/transcript.py`** — the `from_cwd` / `from_session` / `from_transcript` data sources (`GitInfo`, `OpenSpec`, `LoadedSkills`, `RunningSubagent(s)`, `Task`/`TaskList`, `TranscriptUsage`). `info/subagents.py` also holds `read_last_prompt_ts` (the prompt-boundary marker) and the cohort-visibility logic (`RunningSubagents.visible`).
- **`themes.py`** — `Theme`, `ModelColors`, the `THEMES` registry (`CLAUDE_DARK`, `CLAUDE_LIGHT`, `CATPPUCCIN_*`), `resolve`.
- **`info/__init__.py`** — `SessionView` (lazy gather seam) and `_fmt_elapsed`. `SessionView` takes `session: SessionInfo`, `cfg: Config`, and an optional frozen `now: float`. Every derived field is a `@cached_property` — `git`, `skills`, `subagents`, `tasks`, `transcript_usage`, `changes`, `session_cost`, `session_inout`, `elapsed` — so a narrow render pays only for the fields it reads. Module-level `_fmt_elapsed(mtime, now) -> str` is the pure elapsed formatter. `info` sits below `renderer` / `layout` in the DAG and never imports them.
- **`layout.py`** — the layout pipeline (see below).
- **`ops/demo.py`** — the hermetic visual harness (lives outside the package, under `ops/`; see checklists).

### Layout pipeline (`layout.py`)

`RowSpec` (`@dataclass`) carries `kind ∈ {top_border, bottom_border, separator, separator_dim, content}` plus `content`/`bg_lead`/`bg_trail`/`pill_flush`/`ups`/`downs`/`pill`/`pill_edge`/`right_pill`. A `LayoutSpec` (`width`, `fill`, `session_id`, `rows`) is built by one of `build_narrow(view, width, r, soft_limit)` / `build_medium(view, width, r, soft_limit)` / `build_wide(view, tick, width, r, soft_limit)`, then `render_layout(spec, r)` walks rows and dispatches to the matching `Renderer`/`BorderRenderer` method. `append_error_row` is a helper here too. Builders consume a `SessionView` (wide also a `TickRecord`) and do only geometry — they no longer import the six readers or perform any I/O themselves.

**Where to make a change:**

- Section content (a row's text) → the corresponding `Renderer` helper in `renderer.py`.
- Row order, conditional rows, elbow threading → the relevant `build_*` in `layout.py`. Never edit `render_layout` to special-case a layout; thread it through `RowSpec` instead.
- New border style → `BorderRenderer` (`render/borders.py`), then a new `RowSpec.kind` branch in `render_layout`, then use it from a builder.
- New gradient/sparkline maths → `GradientEngine` (`render/gradient.py`). Add a `Renderer` delegator only if existing tests/callers expect it on `Renderer`.
- New token/subagent metric maths → `render/metrics.py` (pure functions), called from a `Renderer` helper.
- A new glyph/colour constant → `constants.py`.
- A new field off the stdin payload → a typed view in `session.py`.
- A new data source (a new on-disk reader) → a module under `info/`, then a `@cached_property` on `SessionView` that constructs it.
- A new derived session value (git, skills, cost, elapsed, …) → add a `@cached_property` to `SessionView` in `info/__init__.py`. If it depends on the per-render `TokenLog`/`TokenRate` writes, put it in `TickRecord` (`tokens.py`) / `record_tick` (`app.py`) instead, and thread it into `build_wide` as a `TickRecord` field.

## Pre-edit checklist

Run all four before editing:

1. **Read `CONTEXT.md`** at repo root. The terms Billed Input, Cache Read, Output, Day Total, Context Window Size, Compaction-Risk Zone, Five-Hour Limit, Seven-Day Limit are canonical — don't rename or alias them in code without a paired update.
2. **Catalogue PUA glyphs on touched lines.** Scan the package (glyphs can appear in any module, though most are hoisted into `constants.py`):
   ```bash
   python3 -c "
   import sys
   for path in sys.argv[1:]:
       for ln, line in enumerate(open(path), 1):
           for c in line:
               cp = ord(c)
               if 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0xFFFFD:
                   print(f'{path}:{ln}  U+{cp:05X}  {c!r}')
   " claude/yas/*.py claude/yas/info/*.py claude/yas/render/*.py
   ```
   Any hit on a line you plan to Edit triggers the **PUA refactor rule** below.
3. **Baseline tests**: `make test` (or `uv run pytest -q`). Note pass count.
4. **Baseline demo**: `make demo` (or `make statusline/test`, both run `uv run python ops/demo.py`). It animates 60 frames in place via cursor escapes; eyeball the final frame and the elbow alignment as it crosses layout thresholds (narrow → medium → wide on `$COLUMNS`). For static snapshot images, `make demo/img` (writes scenario PNGs into `demo/`, honours `COLUMNS=`). For a single piped frame when you need stdout, render one directly: `COLUMNS=160 uv run python claude/statusline_command.py < ops/session-info-example.json` (no transcript-derived rows; enough for border math). For a precise, diff-able baseline instead of eyeballing colour, capture the snapshots as ANSI-stripped text via the **yas-demo-text** skill: `make demo/img && .claude/skills/yas-demo-text/scripts/demo-text.sh && cp -r demo/text /tmp/yas-base`.

## PUA refactor rule (mandatory before editing)

Nerd Font icons in this repo live in the Unicode Private Use Area (U+E000–U+F8FF and U+F0000–U+FFFFD). Literal PUA glyphs in source are invisible in many editors, render as `□` in others, and **get dropped through chat/agent round-trips** — which makes `Edit.old_string` matching fail with a stale-looking "string to replace not found" error.

If a line you need to Edit contains a raw PUA glyph, **hoist the glyph to a named constant in `constants.py` first**, then Edit. No exceptions.

Convention (matches the existing block in `constants.py`):

```python
# Nerd Font Private Use Area glyphs. Encoded as escapes so Edit, diff, and
# chat round-trips never lose the bytes. Render only in a Nerd-Font-capable
# terminal.
ICON_COST      = '\uefc8'     # nf-md currency-usd       (cost row)
ICON_TOK_RATE  = '\U000f18a7' # nf-md gauge              (t/m rate label)
GLYPH_MODEL    = '\U000f08b9' # nf-md monitor-dashboard  (model row)
GLYPH_THINKING = '\U000f1a53' # nf-md brain              (thinking indicator)
```

Import the constant where needed (`from yas.constants import GLYPH_MODEL`) and reference it in f-strings: `f'{model_clr}{GLYPH_MODEL}  {model_name}...'`. Note that `Renderer.ICON_PATH` holds a *colour code*, not a glyph — don't reuse that namespace for glyphs. New glyph constants go in `constants.py` alongside `ICON_COST`/`GLYPH_MODEL`.

Runtime cost is **zero** — `'\uefc8'` (in source) and the literal glyph compile to the identical `str` object; CPython interns and the `.pyc` cache eliminates parse cost after first load.

### Fallback when refactor isn't feasible mid-task

If the line has a PUA glyph and you genuinely can't refactor first (e.g., user is mid-edit and asked for one surgical change), use a Bash heredoc with `python3` that reads, `str.replace`s, and writes. Python preserves the bytes exactly:

```bash
python3 << 'PY'
path = 'claude/yas/renderer.py'
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

- **Never** use `len()` for column math. Use `_visible_width` (`render/text.py`) — it strips ANSI escapes via `_ANSI_RE` (`constants.py`) and counts wide chars (BMP emoji `0x1F300–0x1FAFF`) as 2.
- Nerd Font PUA chars count as width 1. Correct in a Nerd-Font terminal; would be wrong elsewhere, but elsewhere isn't supported.

### Column indexing on borders (`render/borders.py`)

- `border_top(width, session_id='', downs=..., fill=..., pill=...)`, `border_separator(width, ups=...)`, `border_separator_dim(width, downs=..., ups=..., pill=..., pill_edge=...)`, `border_bottom(width, ups=...)` take **1-indexed visual positions** of the inline `│` they should attach an elbow to. Live on `BorderRenderer`; `Renderer` has matching delegators.
- `border_line(content, width, fill=..., bg_lead='', bg_trail='', pill_flush=False, right_pill='')` wraps content as `│ <content>...│`. Content starts at visual column 2, which is **col-form 3** (1-indexed). `right_pill` paints a pill segment flush to the right edge.
- A `Pill` passed to `border_top` / `border_separator_dim` paints itself across `[pill.start, pill.end]` using `border_char(col, edge)` instead of the default top/separator glyph. `pill_edge='top'` is used when the pill sits *below* the separator.

### vsep convention

The vertical divider inside a content row is the 5-char string `'  │  '` (two spaces, pipe, two spaces). The `│` sits at vsep-index 2.

```python
vsep = f'  {self.BORDER}│{self.R}  '   # visible width 5; │ at offset 2
```

### Section helpers that participate in dividers return `(line, div_offset)`

When a section contributes a `│` that should grow elbows on the surrounding borders, the helper returns `(line, div_offset)` where `div_offset` is the **0-indexed visible position of the `│` inside `line`**. Examples: `model_section_compact`, `model_right_section`, `tokens_cost` (which returns `(lines, vsep_cols, …)`).

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

## Layout-spec rules (`layout.py`)

- A `build_*` function returns a fully-populated `LayoutSpec`. Don't push rendering side effects into it; only build `RowSpec`s.
- New row types need: a new `kind` string, a branch in `render_layout`, and a `BorderRenderer` method (if it draws a border) or a `Renderer` section helper (if it's content).
- Conditional rows: append to a local `rows: list[RowSpec]` and assign `spec.rows = rows` at the end. See `build_wide` for the canonical pattern with optional `plugins_line`, `task_row`, and `openspec_bars`.
- When a row drops out (e.g., no plugins), the surrounding `ups`/`downs` need to be re-threaded — `build_wide` carries a `next_ups`/`pending_ups` local and a `sep_kind` helper for this. Don't try to "fix it up" inside `render_layout`.
- Pill threading: when the pill is active, the row immediately under the top border uses `pill_flush=True` and an empty `bg_lead`; the surrounding `top_border` / `separator_dim` receive the same `Pill` object. When the pill is *inactive*, you fall back to `bg_lead`/`bg_trail` and elbow `ups`/`downs`.

## Post-edit checklist

1. **`make test`** (`uv run pytest -q`) — must be green. The pass count should match the baseline plus any tests you added.
2. **`make demo`** — eyeball the animation:
   - Every `┬` in a top border lines up with a `│` in the row beneath it and a `┴` in the separator below.
   - Pill colours flow continuously across the top, sides, and bottom of the model row.
   - Resize the terminal narrower/wider during the run to verify the narrow ↔ medium ↔ wide thresholds.
   - For an exact comparison, re-strip and diff against the baseline from the pre-edit step: `make demo/img && .claude/skills/yas-demo-text/scripts/demo-text.sh && diff -ru /tmp/yas-base demo/text`. Every moved cell shows up as a line diff — this catches off-by-one column bugs the eye misses across the 60-frame animation.
3. **Tests** — any behaviour change needs a test added or updated. Tests resolve the package via `pythonpath = ["claude"]` and import modules as `yas.<module>` / `yas.info.<module>` / `yas.render.<module>`; `conftest.py` exposes a `strip_ansi` fixture (from `test/helper.py`) and a `tmp_home` fixture that patches `CLAUDE_DIR` across `yas.app`/`yas.config`/`yas.constants`/`yas.session`/`yas.info.subagents`/`yas.tokens`. Width-sensitive assertions go through `_visible_width`. Put new tests in the file that matches the layer touched: `test_gradient_math.py`, `test_borders.py`, `test_model_section.py`, `test_context_line.py`, `test_openspec_bar.py`, `test_tokens_cost.py`, `test_config.py`, `test_layout_seam.py`, `test_subagent_rows.py`/`test_subagent_metrics.py`/`test_cohort_visibility.py` (subagents), `test_info.py` (denominator math, `_fmt_elapsed`, laziness), etc. Layout tests inject a `SessionView` directly — construct one with a known `SessionInfo` and `Config` rather than calling the builders with raw reader data.
4. **`CONTEXT.md`** — if any displayed term changed (label, glyph meaning, what a number represents), update the glossary in the same change.

## Multi-session observer

`claude/mon.py` aggregates every active session's statusline into a single alternate-screen TUI. It imports the public `render` / `resolve_theme` callables from `yas.app`. The supporting package at `claude/mon/` has four sub-modules: `discovery.py` (finds active sessions via `~/.claude/projects/*/*.jsonl` mtimes and indexes the `statusline.<session_id>.json` payloads that `app.main` writes under `~/.claude/statusline-output/`), `lifecycle.py` (classifies sessions as bright/dim/removed and applies the SGR-faint dim post-processing), `layout.py` (header/footer formatting, empty/narrow body stubs, overflow clipping, rate-limit and cost aggregation), and `tui.py` (alt-screen entry/exit, `RefreshClock`, SIGWINCH handler, CLI argument parsing). Launch it with `make mon/run`.

## Sibling skills

`python-style` applies as usual when touching `.py` files. This skill adds the statusline-specific rules on top. After a render change, use **yas-demo-text** to turn `make demo/img` snapshots into ANSI-stripped plain text for a before/after `diff` (see the demo steps above) — the reliable way to confirm column math instead of eyeballing the coloured animation.
