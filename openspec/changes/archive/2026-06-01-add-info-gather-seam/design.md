## Context

The render layer's three builders (`build_narrow/medium/wide` in `layout.py:90-348`) each gather their own data inline: twelve reader calls, the `session_inout` denominator arithmetic, and — in `build_wide` — the `TokenLog.update` / `TokenRate.update` disk writes followed by `compute_day_cost` reading the log back. The gather logic is triplicated and width-coupled, and `layout` imports the six filesystem readers directly, so a builder cannot be tested without touching the real filesystem. `SessionInfo` is a clean, deep parse of the stdin JSON, but the *derived* session state has no home. This change adds that home: a `SessionView` gather module (`info`) sitting below the render layer.

The design was settled through an interface-design pass (four competing sketches). The chosen shape is the minimal one — a plain dataclass of lazy cached fields delegating to the existing readers — with three targeted grafts.

## Goals / Non-Goals

**Goals:**
- One `SessionView` module that turns `SessionInfo` + `Config` into all derived session state, gathered lazily and read at most once each.
- `layout` builders consume a view and do only geometry; they no longer import the readers or touch the filesystem.
- Per-render disk writes (`TokenLog`/`TokenRate`) move out of the render path into an `app`-owned `record_tick` step.
- The seam is testable directly: layout tests inject a view; a new `test_info.py` covers the gather logic.

**Non-Goals:**
- No change to rendered output, config precedence, or any runtime/public contract.
- No change to `statusline_command.py`, the demo, themes, or the rendering algorithms.
- No change to the six readers' internals or their individually-stubbable classmethod seams.
- No performance work beyond preserving today's lazy I/O profile (the separate `improve-latency` concern).

## Decisions

### D1: Lazy `@cached_property` view, not eager-all or per-width

`SessionView` holds `session` + `cfg`; each derived field is a `@cached_property` that reads on first access and caches. Narrow renders touch only the fields they draw, so the git subprocess / transcript scan / openspec walk never fire for a width that does not show them — preserving today's lazy I/O profile.

- *Alternative — eager `gather()` reads everything*: simplest interface and a trivially-constructible frozen dataclass, but a narrow render pays for I/O it discards. Rejected on the statusline's per-tick latency budget.
- *Alternative — per-width `gather(session, cfg, tier)`*: preserves the I/O savings but returns a struct with half its fields `None` depending on a `tier` arg the caller must keep in sync. Dishonest interface, rejected.

### D2: Pure-read view; writes isolated in `record_tick` / `TickRecord`

The view performs no disk writes. The `TokenLog.update` / `TokenRate.update` writes (and the `compute_day_cost` that depends on them) move into `record_tick(session, usage) -> TickRecord`, owned by `app` and placed beside the existing per-render payload write (`app.py:65-69`) — the established home for per-render side effects. `app` threads the `TickRecord` into `build_wide`. Everything on `SessionView` is therefore derivable from `session` + `cfg` alone; Day Total / day-cost, which depend on the persist, are carried separately so they cannot masquerade as gathered facts.

- *Alternative — view owns the writes*: one call yields a complete view, but constructing a view in any test would rewrite the real token log, and "gather" would dishonestly mutate state. Rejected.
- *Alternative — `day_cost` as a `SessionView` field threaded in*: convenient for `build_wide`, but conflates a persist-dependent value with self-derived facts and muddies the deletion test. Rejected in favour of the `TickRecord` carrier.

### D3: Geometry stays render-side

`fill`, the pill percentage, model anchor/shift, and `effort_for_bg` call `Renderer` and remain in the builders. `SessionView` holds only data. This keeps `info` strictly below the render layer in the DAG (it never imports `renderer`).

### D4: Direct delegation, no injected port

The view calls the readers' classmethods directly. The dependencies are all local-substitutable (filesystem reads with temp-dir/fixture stand-ins), so per seam discipline a port would be a single-production-adapter indirection with no second backend to justify it. Tests substitute by pointing a `SessionInfo` at fixtures, or by stubbing a reader classmethod.

- *Alternative — `SessionSource` port + `FsSource`/`FakeSource` adapters*: makes laziness a mechanical call-count assertion, but adds a permanent production adapter and a threaded constructor arg for a seam that will never have a second real backend. The laziness invariant can be pinned with a counting monkeypatch in one test instead. Rejected.

### D5: Frozen injectable clock

`SessionView(session, cfg, *, now=None)` captures `now` once. `elapsed` and task-freshness decisions read through the view use that single value, giving cross-row consistency within one render and deterministic tests without monkeypatching `time.time`.

### D6: `@cached_property`, not a `@fact` registry

Adding a derived fact is already one `@cached_property` method, so a bespoke self-registering decorator buys no real extensibility and costs static legibility (a typo would fail at call time). Stdlib `functools.cached_property` is the whole mechanism.

### D7: Create-then-collapse, fan-out-friendly task structure

The new module is created additively first (the monolithic builders keep working against their inline copies), then the builders collapse onto it in one gated step. The task list is grouped so independent pieces — the `info` module body, the `record_tick` step, and the new `test_info.py` — can be picked up by separate workers in parallel before the serial collapse, mirroring the create-only-waves discipline of the prior module split.

## Risks / Trade-offs

- **Crooked borders / pill misalignment the unit tests miss** → the builders are width-sensitive and partly visual. Mitigation: run `make statusline/test` (the demo) after the collapse step, eyeballing elbow/pill alignment across the narrow/medium/wide thresholds.
- **A field accessed for its side-of-effect ordering** → `record_tick` must run so `day_cost` reflects this tick; it is sequenced explicitly in `app` before `build_wide`, not hidden in the view. Mitigation: the `TickRecord` is an explicit `build_wide` parameter, so the ordering is visible at the call site.
- **Double transcript read** → `record_tick` needs `usage` and so does the view; `app` reads `view.transcript_usage` (cached) and hands it to `record_tick`, so the transcript is scanned once. Mitigation: pass the view's cached usage into `record_tick` rather than re-reading.
- **The six leaf fields are thin pass-throughs** → individually shallow, but the module as a whole passes the deletion test (delete it and the twelve calls + the denominator + the writes re-smear across three builders). Accepted: the depth is in consolidation + laziness + the single `session_inout`, not in each leaf.
- **Transient duplication mid-change** → the gather logic exists in both `info` and the builders until the collapse step. Mitigation: the collapse is one commit, gated on a green suite + demo pass; the un-repointed builders keep passing against their inline copies until then.

## Migration Plan

Work on `refactor-into-modules` (or a fresh `add-info-gather-seam` branch). Create `info.py` and `record_tick` additively (suite stays green), then collapse the builders and repoint tests in one gated step, verifying with `uv run pytest -q` and `make statusline/test`. Rollback before the collapse is deleting the new files; the collapse commit is the only irreversible-feeling step. Finally update the `CONTEXT.md` Module map (the glossary terms are already added).

## Open Questions

- None blocking. Branch name (`refactor-into-modules` vs a fresh branch) is the implementer's choice.
