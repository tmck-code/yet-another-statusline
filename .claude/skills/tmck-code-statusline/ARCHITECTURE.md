# Architecture map (post-package-split)

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
- **`renderer.py`** (top level) — **`Renderer`** composes the two (`self.gradient`, `self.border`) and adds every section helper (`path_git`, `path_git_compact`, `fit_path`, `model_section_compact`, `model_right_section`, `model_right_section_compact`, `plugins_skills`, `subagent_activity`, `subagent_row`, `task_row`, `tokens_cost`, `context_line`, `context_line_compact`, `openspec_bar`, `spec_gradient_bar`, `burndown_trend`, `helper`, the colour pickers, `vsep_block`, …). Keeps thin delegators (`gradient_color`, `border_top`, …) for backward-compat callers and tests. Module-level `LEVEL_PCT` and `TOOL_ARG_KEY` dicts live here too.

Supporting modules:

- **`render/pill.py`** — `Pill` (`@dataclass`): the model-effort coloured pill. `active`, `gradient_fg(col)`, `border_char(col, edge)`, `border_fg(col)`. Border helpers accept `pill: Pill | None` and `pill_edge: 'top' | 'bottom'`.
- **`render/text.py`** — width/format primitives: `_visible_width`, `_is_wide`, `terminal_width`, `_middle_ellipsis`, `fmt_tok`, `fmt_dur`, `sparkline_width`.
- **`render/metrics.py`** — `burndown_delta`, `subagent_avg_tpm`, `subagent_share`.
- **`render/tasks_view.py`** — task-row geometry: `WindowSlice`, `fmt_duration`, `total_elapsed`, `select_window` (the windowing/elapsed maths behind `Renderer.task_row`).
- **`constants.py`** — width thresholds (`MIN_WIDTH=40`, `NARROW_WIDTH=55`, `MEDIUM_WIDTH=80`, `DEFAULT_MAX_WIDTH=140`), `_ANSI_RE`, `BarChars`, all `CLR_*` colour codes, `RESET`/`BOLD`/`ITALIC`, the five-hour / seven-day limit constants, `RAINBOW_PALETTE`, `CLAUDE_DIR`, and **every Nerd Font PUA glyph constant** (`ICON_COST`, `GLYPH_MODEL`, `SPARK_*`, `PILL_*`, …). This is the hoist target for the PUA rule in `SKILL.md`.
- **`tokens.py`** — `TokenAccounting` (static `rates_for`, `session_cost`, `day_cost`), `TokenLog` and `TokenRate` (the on-disk t/m rate history), the `TickRecord` dataclass, and module-level `compute_session_cost` / `compute_day_cost`. Don't inline rate math elsewhere.
- **`session.py`** — `SessionInfo.from_dict` and every typed view of the stdin payload (`Model`, `OutputStyle`, `Effort`, `Thinking`, `Workspace`, `Cost`, `ContextWindow`, `RateLimits`, `RateBucket`, `CurrentUsage`, …) plus `_as_int/_as_float/_as_str` coercers.
- **`config.py`** — `Config` (frozen dataclass): merges `yas.toml`, env vars, and argv; `soft_limit_for(model_id, display_name)`.
- **`info/git.py`** / **`info/openspec.py`** / **`info/skills.py`** / **`info/subagents.py`** / **`info/tasks.py`** / **`info/transcript.py`** — the `from_cwd` / `from_session` / `from_transcript` data sources (`GitInfo`, `OpenSpec`, `LoadedSkills`, `RunningSubagent(s)`, `Task`/`TaskList`, `TranscriptUsage`). `info/subagents.py` also holds `read_last_prompt_ts` (the prompt-boundary marker) and the cohort-visibility logic (`RunningSubagents.visible`).
- **`themes.py`** — `Theme`, `ModelColors`, the `THEMES` registry (`CLAUDE_DARK`, `CLAUDE_LIGHT`, `CATPPUCCIN_*`), `resolve`.
- **`info/__init__.py`** — `SessionView` (lazy gather seam) and `_fmt_elapsed`. `SessionView` takes `session: SessionInfo`, `cfg: Config`, and an optional frozen `now: float`. Every derived field is a `@cached_property` — `git`, `skills`, `subagents`, `tasks`, `transcript_usage`, `changes`, `session_cost`, `session_inout`, `elapsed` — so a narrow render pays only for the fields it reads. Module-level `_fmt_elapsed(mtime, now) -> str` is the pure elapsed formatter. `info` sits below `renderer` / `layout` in the DAG and never imports them.
- **`layout.py`** — the layout pipeline (see below).
- **`ops/demo.py`** — the hermetic visual harness (lives outside the package, under `ops/`; see `SKILL.md`'s checklists).

## Layout pipeline (`layout.py`)

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

## Multi-session observer

`claude/mon.py` aggregates every active session's statusline into a single alternate-screen TUI. It imports the public `render` / `resolve_theme` callables from `yas.app`. The supporting package at `claude/mon/` has four sub-modules: `discovery.py` (finds active sessions via `~/.claude/projects/*/*.jsonl` mtimes and indexes the `statusline.<session_id>.json` payloads that `app.main` writes under `~/.claude/statusline-output/`), `lifecycle.py` (classifies sessions as bright/dim/removed and applies the SGR-faint dim post-processing), `layout.py` (header/footer formatting, empty/narrow body stubs, overflow clipping, rate-limit and cost aggregation), and `tui.py` (alt-screen entry/exit, `RefreshClock`, SIGWINCH handler, CLI argument parsing). Launch it with `make mon/run`.
