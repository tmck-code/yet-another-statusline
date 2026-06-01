## Context

`claude/statusline_command.py` is a single 3,200-line module. It is the file the `yas` plugin invokes directly (`settings.json` hardcodes `.../claude/statusline_command.py`), and ~40 test files plus `claude/mon.py` couple to it as a flat namespace (`import statusline_command as sl`). The code already falls into clean horizontal bands, and a prior investigation confirmed the bands form an acyclic dependency graph: the filesystem readers reference zero render-layer symbols, and `config`/`session`/`tokens` reference zero glyph/colour constants.

Four hard constraints frame the work:

1. **Frozen entrypoint filename** — `claude/statusline_command.py` must keep its path and name.
2. **Script-by-path execution** — the runtime invokes `python <abs>/claude/statusline_command.py`, so `sys.path[0]` is `claude/` and `import statusline.x` resolves at runtime. pytest, however, sets no `pythonpath` today and loads the module via a `spec_from_file_location` shim in `conftest.py`; `themes.py` is loaded via a second `__file__`-relative shim.
3. **Plugin distribution** — the whole `claude/` tree ships; no manifest enumerates files, so new modules ship for free.
4. **PUA glyph hazard** — Nerd Font icons live in the Private Use Area; raw glyphs get dropped through agent round-trips. The repo already hoists them to escape-encoded module constants.

## Goals / Non-Goals

**Goals:**
- Decompose the monolith into a layered, acyclic `claude/statusline/` package, one module per concern.
- Reduce `statusline_command.py` to a thin composition entrypoint.
- Give each module a real, independently-importable seam; repoint every test to the module it exercises.
- Remove import-time global config state; resolve `Config` live.
- Structure extraction so independent modules are carved by **parallel subagents** with zero merge conflicts.

**Non-Goals:**
- No behavior change to the rendered output, config precedence, or any public/runtime contract.
- No re-export compatibility shim preserving the flat `sl.*` namespace (this is option b: full repoint).
- No change to `themes.py` internals, the demo, or the rendering algorithms themselves.
- No performance work (that is the separate `improve-latency` concern).

## Decisions

### D1: Module layout (the DAG)

One module per band, importing only from earlier layers:

```
constants            ANSI colours, GLYPH_/ICON_/SPARK_/PILL_ escapes, BarChars,
                     RESET/BOLD/ITALIC, width + rate-limit-window consts, _ANSI_RE
text                 _visible_width, _is_wide, _middle_ellipsis, fmt_tok, fmt_dur,
                     sparkline_width, terminal_width
config               _parse_*, _resolve, _env_sources, _load_toml, _parse_models, Config
session              Model…SessionInfo, _as_*, _parse_iso_to_epoch
metrics              burndown_delta, subagent_avg_tpm, subagent_share
tokens               TokenAccounting, compute_session_cost/day_cost, TokenLog, TokenRate
git skills subagents tasks transcript openspec   one filesystem/transcript reader each
pill                 Pill + pill glyph helpers
gradient             GradientEngine, rainbow_*, model_key, _scale, paint_bg_span, pill_gradient_fg
borders              BorderRenderer
renderer             Renderer (all section helpers)
layout               RowSpec, LayoutSpec, append_error_row, build_*, render_layout
app                  render, resolve_theme, main
```

Leaf-module names (`constants`, `text`, `metrics`, `pill`, `app`) confirmed with the user. **Alternatives considered:** one `render.py` for the whole painter (rejected — keeps the 1,300-line wall, and the three layers already have separate test files); one `sources.py` for all readers (rejected — bundles six independent I/O seams the user wants individually stubbable).

### D2: Parallel execution model — "create-only waves, collapse once"

The danger in parallelizing is N subagents editing the *same* monolith. The rule that removes all conflict: **during the parallel phase, no subagent edits `statusline_command.py`.** Each extraction job only (a) creates its new `statusline/<module>.py` by copying its band out of a read-only snapshot of the monolith, and (b) repoints the test file(s) that exercise it. The monolith is left fully intact, so any not-yet-repointed test keeps passing against it (transient code duplication is accepted for the life of the branch).

A module can only be imported once its DAG dependencies exist, so extraction proceeds in **waves**; modules *within* a wave are mutually independent (same DAG layer) and run as parallel subagents:

- **Wave A:** `constants`
- **Wave B (∥):** `text`, `session`, `metrics`, `config`
- **Wave C (∥ — the big fan-out):** `tokens`, `git`, `skills`, `subagents`, `tasks`, `transcript`, `openspec`
- **Wave D (∥):** `pill`, `gradient`
- **Wave E:** `borders`
- **Wave F:** `renderer`
- **Wave G:** `layout`
- **Wave H (serial collapse):** create `app`; rewrite `statusline_command.py` to the 3-line entrypoint; delete the now-duplicated bands from the monolith; add `pyproject` pytest `pythonpath`; delete the conftest spec shim and the themes `__file__` shim; repoint `mon.py`; remove the `CONFIG`/`SOFT_LIMIT`/`MAX_WIDTH` globals and thread `soft_limit` explicitly.

Each parallel job's **definition of done** is local: its new module imports cleanly and its repointed test file(s) pass. The full suite stays green throughout because un-repointed tests still hit the intact monolith. The render chain (D→G) is inherently serial; the parallelism win is Waves B and C (4 + 7 modules).

**Alternative considered:** per-subagent git worktrees with a merge at the end (rejected — every job would still need to edit the one monolith to remove its band, producing guaranteed conflicts; the create-only rule sidesteps this entirely).

### D3: Import path and shim removal

Add `[tool.pytest.ini_options] pythonpath = ["claude"]`. This makes both `import statusline_command` and `import statusline.<module>` resolve under pytest, which in turn lets us delete the `conftest.py` `spec_from_file_location` block and replace the monolith's `__file__`-relative themes loader with `from statusline.themes import Theme, ModelColors, THEMES, CLAUDE_DARK`. Runtime already has `claude/` on `sys.path[0]`, so the same plain imports work for the live command.

### D4: Test import convention

Module-qualified: `import statusline.borders as borders; borders.BorderRenderer(...)`. Preserves the `sl.Foo → borders.Foo` feel, makes each symbol's home obvious at the call site, and keeps from-import lists short. Use `test/conftest.py`'s `strip_ansi` / `_visible_width` helpers unchanged.

### D5: Live config, no globals

`render()` calls `Config.load()` (or accepts an injected `Config`) like `main()`/`resolve_theme()` already do, fixing the documented live-vs-cached inconsistency. `build_narrow/medium/wide` already accept `soft_limit`; callers pass `cfg.soft_limit_for(...)`. The 11 `sl.MAX_WIDTH`/`sl.SOFT_LIMIT` test references become explicit literals or `config.DEFAULT_*` constants. Importing any module performs no env/`yas.toml` read.

## Risks / Trade-offs

- **PUA glyph byte loss during copy-out** → The single highest risk in this repo. Mitigation: the `constants` module (Wave A) is created by copying the existing escape-encoded glyph lines verbatim; subagents reference glyphs only by constant name and never transcribe raw PUA characters. A post-Wave-A check greps the new `constants.py` for raw PUA codepoints and compares the glyph-constant count to the monolith's.
- **Crooked borders pytest won't catch** → Column math is width-sensitive and partly visual. Mitigation: run `make statusline/test` (the subprocess demo) after Waves F, G, and H, eyeballing elbow/pill alignment across the narrow/medium/wide thresholds.
- **Transient code duplication mid-branch** → bands exist in both the monolith and the new module until Wave H. Mitigation: Wave H deletes the bands and a final check asserts the monolith defines no symbol that also lives in a package module (no orphaned duplicates).
- **A repointed test outruns its dependency module** → e.g. `test_borders` repointed before `gradient` exists. Mitigation: the wave ordering is a hard barrier — a wave starts only after the previous wave's modules are committed and importable.
- **`mon.py` / `test_render_callable` reach `render`** → both repointed in Wave H to `statusline.app`; `render`/`resolve_theme`/`MIN_WIDTH` remain importable, just from their real homes.

## Migration Plan

Work on the `improve-latency` branch (or a dedicated `split-statusline-modules` branch). Execute Waves A→H; after each wave run `uv run pytest -q` (must stay green) and, for Waves F/G/H, `make statusline/test`. Rollback is per-wave: because the monolith stays intact until Wave H, aborting before H leaves a working tree with extra (unused) module files and can be reverted by deleting them. Wave H is the only irreversible-feeling step and is gated on a full green suite + demo pass. Finally, add the "Module map" section to `CONTEXT.md`.

## Open Questions

- None blocking. If an external consumer outside this repo ever imported `statusline_command` symbols directly, they would break — but the only known importers are this repo's tests and `mon.py`, both repointed here.
