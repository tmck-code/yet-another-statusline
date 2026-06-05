<!-- AGENT INSTRUCTIONS: Mark each subtask done with TaskUpdate (status: completed) the
     moment it is finished — before starting the next task. This keeps progress visible
     to observers in real time. Subtasks within the same numbered group that have no
     dependency on each other MAY be delegated to parallel subagents; each subagent
     must also mark its own subtask done immediately upon completion. -->

## 1. Understand current code

- [x] 1.1 Read `claude/yas/renderer.py` lines 969–1020 (`context_line`, `context_line_compact`) and `claude/yas/session.py` lines 198–214 (`ContextWindow`, `used_percentage`) to confirm the current formula and what the `ctx` argument carries
- [x] 1.2 Run `make test` and record the baseline pass count

## 2. Fix context_line (wide/medium)

- [x] 2.1 In `context_line()`: replace `total_tokens = ctx.total_input_tokens + ctx.total_output_tokens` with a helper that returns `(fill_ratio, pct_soft)` — using `ctx.used_percentage / 100` when it is not `None` and `>= 0`, falling back to `ctx.total_input_tokens / ctx.context_window_size` (guarded against divide-by-zero), clamped to `[0, 1]`
- [x] 2.2 Remove any remaining addition of `ctx.total_output_tokens` in `context_line()`
- [x] 2.3 Ensure `pct_soft` (the displayed `%` figure) is derived from the same `fill_ratio * 100`, not recomputed from raw tokens

## 3. Fix context_line_compact (narrow)

- [x] 3.1 Apply the same `used_percentage`-preferred / input-only-fallback logic to `context_line_compact()` — tasks 2.1–2.3 replicated for the compact variant

## 4. Tests (can be done in parallel with step 5)

- [x] 4.1 In `test/test_context_line.py` (or create it): add scenario — host-supplied `used_percentage=42.7` → fill `0.427`, label `43%`
- [x] 4.2 Add scenario — `used_percentage=None`, `total_input=80000`, `context_window_size=200000` → fill `0.40`, label `40%`
- [x] 4.3 Add scenario — `used_percentage=None`, output tokens present → fill uses input-only (output tokens excluded)
- [x] 4.4 Add scenario — `used_percentage=-2.0` → fill `0.0`
- [x] 4.5 Add scenario — `used_percentage=None`, `context_window_size=0` → fill `0.0`, no exception

## 5. Re-baseline snapshots (can be done in parallel with step 4)

- [x] 5.1 Run `make demo/img` and inspect any PNG snapshots that include the context row; update any stored baselines that changed

## 6. Verify

- [x] 6.1 Run `make test` — must be green with count ≥ baseline + new tests added
- [x] 6.2 Run `make demo` — eyeball the context row percentage in the animation; confirm it is plausible (not inflated by output tokens)
