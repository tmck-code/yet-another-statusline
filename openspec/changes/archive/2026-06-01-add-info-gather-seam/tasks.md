# Tasks: add-info-gather-seam

> **Working agreement — every agent, main or subagent, READ THIS FIRST.**
>
> 1. **Mark each subtask `- [x]` _immediately_ as soon as it is done** — the instant the
>    edit lands and its local check passes, edit this file and tick the box. Do **not** batch
>    ticks, do **not** wait until the end of a wave, do **not** tick ahead of finishing.
>    The checkbox state in this file is the **single source of truth** for how far the change
>    has progressed; another worker (or the human watching) reads it to decide what to pick up
>    next. A done-but-unticked task looks unstarted and will be duplicated.
> 2. **File-ownership rule for parallel work:** within a wave that runs in parallel, no two
>    workers may edit the same file concurrently. Each task below names the file(s) it owns.
>    If two pending tasks touch the same file, they belong to one worker and run in sequence.
> 3. **Wave gating:** a wave starts only after every box in the waves it depends on is ticked.
>    Waves 1 and 2 are mutually independent and run in parallel. Wave 3 may start once Wave 1
>    is ticked. Wave 4 (the collapse) is serial and starts only after Waves 1–3 are ticked.
>    Wave 5 is serial and last.
> 4. If a task turns out to be already done or not needed, tick it and note `(no-op: <reason>)`
>    inline — never leave a finished-in-effect task unticked.

## 1. Wave A — create `info.py` (parallel with Wave 2; owns `claude/statusline/info.py`, a new file)

- [x] 1.1 Create `claude/statusline/info.py` with a `SessionView` dataclass (`session: SessionInfo`, `cfg: Config`, `now: float = field(default_factory=time.time)`) and the six leaf `@cached_property` fields — `git`, `skills`, `subagents`, `tasks`, `transcript_usage`, `changes` — each delegating to its existing reader classmethod (`GitInfo.from_cwd`, `LoadedSkills.from_transcript`, `RunningSubagents.from_session`, `TaskList.from_session`, `TranscriptUsage.from_transcript`, `OpenSpec.from_cwd(...).changes`).
- [x] 1.2 Add the derived `@cached_property` fields to `info.py`: `session_cost` (`compute_session_cost(session.model, transcript_usage)`), `session_inout` (`(billed_in + cache_read + out) + Σ(subagent total_input + output)`), and `elapsed` (a `stat`-based read that calls a pure module-level `_fmt_elapsed(mtime: float | None) -> str`).
- [x] 1.3 Confirm `info.py` imports only downward (`session`, the six readers, `metrics`, `tokens` for cost only, `config`, stdlib) and references no symbol from `renderer`, `pill`, `gradient`, `borders`, or `layout`; verify `python -c "import statusline.info"` is clean.

## 2. Wave A — new tests for `info` (parallel with Wave 1; owns `test/test_info.py`, a new file)

- [x] 2.1 Create `test/test_info.py` asserting `session_inout` equals billed-in + cache-read + output plus each subagent's `total_input + output`, from a `SessionView` built over known usage and a known subagent set.
- [x] 2.2 Add `_fmt_elapsed` cases: `None` mtime → `''`, sub-hour → `Nm`, multi-hour → `HhMm`.
- [x] 2.3 Add a laziness test: wrap a reader classmethod with a call-counter (monkeypatch), access only `view.subagents`, and assert the git / transcript / openspec readers were not called.

## 3. Wave B — `record_tick` (serial after Wave 1; owns `claude/statusline/app.py`, additive only)

- [x] 3.1 Add a `TickRecord` dataclass (`token_log`, `day_cost`, `tok_rate`) and `record_tick(session, usage) -> TickRecord` to `app.py`, lifting `TokenLog.update` / `TokenRate.update` / `compute_day_cost` from `build_wide`. Additive — do **not** yet remove them from `build_wide`; suite stays green.

## 4. Wave C — collapse the builders (serial, gated on Waves 1–3; one coordinated worker — touches `layout.py` and `app.py`)

- [x] 4.1 Repoint `build_narrow` / `build_medium` / `build_wide` in `layout.py` to take a `SessionView` (wide also a `TickRecord`) and read every gathered value off the view; drop the redundant `session` param where `view.session` covers it.
- [x] 4.2 Delete from `layout.py` the inline reader calls, the `session_inout` arithmetic, the `TokenLog`/`TokenRate`/`compute_day_cost` block, and `elapsed_from_transcript`; remove the now-unused imports of `git`, `skills`, `subagents`, `tasks`, `transcript`, `openspec`.
- [x] 4.3 Rewire `app.render` / `app.main`: construct `SessionView(session, cfg)`, call `record_tick(session, view.transcript_usage)` (cached usage — no double transcript scan), and width-dispatch passing `view` (plus the `TickRecord` for wide).
- [x] 4.4 Repoint layout tests (`test_layout_seam`, `test_layout_subagent_rows`, and any other builder tests) to construct a `SessionView`; delete coverage that only exercised gather-through-the-builder; leave the per-reader tests untouched.

## 5. Wave D — verify & document (serial, last; owns `CONTEXT.md`)

- [x] 5.1 Run `uv run pytest -q` and confirm the full suite is green.
- [x] 5.2 Run `make statusline/test` and eyeball elbow/pill alignment across the narrow / medium / wide width thresholds.
- [x] 5.3 Update the `CONTEXT.md` Module map: add the `info` row, and update the `layout` row (consumes a `SessionView`, no longer imports the readers) and the `app` row (adds `record_tick` / `TickRecord`).
- [x] 5.4 Run `openspec validate add-info-gather-seam` and confirm the change validates.
