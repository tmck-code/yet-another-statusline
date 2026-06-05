## Why

The wide layout's "elapsed" field is currently derived from the transcript file's `mtime` — the time since the last transcript write, which is an **idle metric** (how long since something was logged), not the session's actual compute duration. Claude Code already provides the authoritative wall-clock session duration as `cost.total_duration_ms` on the stdin payload. Using it makes the elapsed figure accurate and consistent with what Claude Code tracks internally.

## What Changes

- `SessionView.elapsed` in `info/__init__.py` will be rewritten to return a formatted duration derived from `session.cost.total_duration_ms` (milliseconds → `fmt_dur` / human-readable string), instead of computing `now − transcript_mtime`.
- `_fmt_elapsed` will be updated or replaced to accept a duration in milliseconds.
- The `transcript_mtime` path that was used solely for `elapsed` will be removed from `SessionView.elapsed` (the transcript is still scanned for `transcript_usage`; only the elapsed-specific mtime read is removed).
- Wide-layout snapshot baselines showing an elapsed tail will be re-baselined.

## Capabilities

### New Capabilities

- `session-elapsed-accuracy`: The displayed elapsed value reflects actual session compute time from the host payload, not the idle-since-last-transcript-write heuristic.

### Modified Capabilities

*(none — replaces the implementation of an existing field; the rendered label and position are unchanged)*

## Impact

- `claude/yas/info/__init__.py`: `SessionView.elapsed`, `_fmt_elapsed`
- `claude/yas/session.py`: `Cost.total_duration_ms` (already parsed; newly consumed by `elapsed`)
- Tests: `test_info.py` — the elapsed scenario will change from mtime-based to duration-based inputs
