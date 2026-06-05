## Context

`SessionView.elapsed` in `info/__init__.py` computes `now − transcript_mtime` — the wall time since the last line was appended to the transcript JSONL. This is an idle metric: it resets to zero on every tool call, not a running total of session duration.

Claude Code already tracks the real session wall-clock duration in milliseconds as `cost.total_duration_ms` on the stdin payload. This field is parsed into `session.cost.total_duration_ms` (`session.py:178,187`) but is never consumed by the renderer.

`_fmt_elapsed` currently accepts a Unix timestamp (`mtime`) and a `now` to compute a delta. It needs to accept a raw duration in milliseconds instead.

## Goals / Non-Goals

**Goals:**
- Derive `SessionView.elapsed` from `session.cost.total_duration_ms` (ms → formatted string)
- Remove the transcript mtime stat from the `elapsed` property (transcript is still scanned for `transcript_usage`; only the elapsed-specific mtime read is removed)
- Update `_fmt_elapsed` (or replace with a `_fmt_duration_ms` helper) to take milliseconds

**Non-Goals:**
- Changing the position, label, or visual style of the elapsed field in the layout
- Altering any other use of the transcript scan

## Decisions

**Replace `_fmt_elapsed(mtime, now)` with `_fmt_duration_ms(ms)`**: The new signature is simpler (no `now` needed) and clarifies the input unit. Keep `_fmt_elapsed` as a one-line wrapper calling `_fmt_duration_ms(max(0, now - mtime) * 1000)` if any test or caller still needs it, otherwise delete it.

**`elapsed` property reads `self.session.cost.total_duration_ms`**: No file stat, no `now` dependency. The value is already in memory from the parsed payload.

**Format**: Preserve the existing display format — `Nm` for under an hour, `HhMm` for ≥ 1 h — so the layout geometry is unchanged.

## Risks / Trade-offs

- Sessions started before Claude Code began populating `total_duration_ms` will show `0s` or `0m` rather than an idle-based estimate. This is a minor regression for very old sessions but is the correct trade-off for accuracy.
- Snapshot baselines that show an elapsed tail need re-baselining.
