## Why

The data-gathering for a render is smeared inline across `build_narrow`, `build_medium`, and `build_wide` in `layout.py` — twelve reader calls plus the `session_inout` denominator and the `TokenLog`/`TokenRate` writes, triplicated and width-coupled. The render layer (`layout`) reaches all the way down through six filesystem reader seams, and `layout`'s builders can only be tested by touching the real filesystem. There is no `info` module: a render module is doing the gathering. This change introduces the missing seam.

## What Changes

- Add a new `claude/statusline/info.py` exposing `SessionView` — a lazy, pure-read view of all *derived* session state (git, loaded skills, running subagents, tasks, transcript usage, openspec changes, elapsed, session cost, `session_inout`), built once per render from a parsed `SessionInfo` + `Config`. Every field is a `@cached_property`, so a narrow render pays only for the sources it draws.
- Move the per-render disk writes out of `build_wide` into a `record_tick(session, usage) -> TickRecord` step owned by `app`, sitting beside the existing `statusline-output` payload write. `TickRecord` bundles `token_log`, `day_cost`, and the token rate; **Day Total** and day-cost are threaded into the wide builder rather than gathered.
- Relocate `elapsed_from_transcript` out of `layout.py` into `info`, split into an impure mtime read + a pure `_fmt_elapsed` formatter.
- Repoint `build_narrow/medium/wide` to consume a `SessionView` (wide also a `TickRecord`); delete the inline reader calls, the `session_inout` arithmetic, and the token-log writes from `layout.py`. `layout` no longer imports `git`, `skills`, `subagents`, `tasks`, `transcript`, or `openspec`.
- Repoint layout tests to construct a `SessionView`; keep the per-reader tests unchanged; add `test_info.py` (denominator math, `_fmt_elapsed`, laziness).
- No change to rendered output, config precedence, or any runtime contract.

## Capabilities

### New Capabilities
- `statusline-info`: the `SessionView` gather seam — a lazy, pure-read, render-independent view of derived session state, plus the `record_tick`/`TickRecord` boundary that keeps per-render disk writes out of the view.

### Modified Capabilities
- `statusline-packaging`: the layered acyclic DAG gains the `info` module (after the readers/`tokens`, below `renderer`); `layout` consumes `info` instead of importing the six readers directly.

## Impact

- New file: `claude/statusline/info.py`. Modified: `claude/statusline/layout.py` (builders consume a view; readers/`elapsed_from_transcript` removed), `claude/statusline/app.py` (`record_tick`/`TickRecord`, view construction, width dispatch).
- Tests: layout tests repointed; new `test/test_info.py`; per-reader tests untouched.
- No change to `statusline_command.py`, the demo output, themes, or the rendering algorithms. No new third-party dependencies.
