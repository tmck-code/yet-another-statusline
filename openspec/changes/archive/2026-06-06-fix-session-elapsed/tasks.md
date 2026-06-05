<!-- AGENT INSTRUCTIONS: Mark each subtask done with TaskUpdate (status: completed) the
     moment it is finished — before starting the next task. This keeps progress visible
     to observers in real time. Tasks 4 and 5 are independent and MAY be delegated to
     parallel subagents; each subagent must mark its own subtask done immediately. -->

## 1. Understand current code

- [x] 1.1 Read `claude/yas/info/__init__.py` lines 30–135 (`_fmt_elapsed`, `SessionView.elapsed`) to understand the current mtime-based implementation
- [x] 1.2 Read `claude/yas/session.py` lines 175–190 (`Cost` dataclass) to confirm `total_duration_ms` field name and type
- [x] 1.3 Run `make test` and record the baseline pass count

## 2. Update the format helper

- [x] 2.1 Add a `_fmt_duration_ms(ms: int) -> str` function in `info/__init__.py` that converts milliseconds to `Nm` (< 1 h) or `HhMm` (≥ 1 h) — same output format as `_fmt_elapsed` produces today
- [x] 2.2 If `_fmt_elapsed` is used by any other caller, keep it as a wrapper: `_fmt_elapsed(mtime, now) -> str` calls `_fmt_duration_ms(int(max(0, now - mtime) * 1000))`. If it has no other callers, remove it.

## 3. Rewrite SessionView.elapsed

- [x] 3.1 Replace the body of `SessionView.elapsed` with: return `_fmt_duration_ms(self.session.cost.total_duration_ms)`
- [x] 3.2 Remove the `transcript_path` stat / mtime read that was done exclusively for `elapsed` (ensure the transcript is still scanned normally for `transcript_usage`)

## 4. Tests (can be done in parallel with step 5)

- [x] 4.1 In `test/test_info.py`: add scenario — `total_duration_ms=807000` (13m27s) → `elapsed == '13m'`
- [x] 4.2 Add scenario — `total_duration_ms=5580000` (1h33m) → `elapsed == '1h33m'`
- [x] 4.3 Add scenario — `total_duration_ms=0` → `elapsed` is `''` or `'0m'` (match chosen behaviour)
- [x] 4.4 Add scenario — accessing `view.elapsed` alone does NOT trigger a file stat (assert no `Path.stat` call)

## 5. Re-baseline snapshots (can be done in parallel with step 4)

- [x] 5.1 Run `make demo/img` and update any wide-layout snapshot baselines that show an elapsed tail value

## 6. Verify

- [x] 6.1 Run `make test` — must be green with count ≥ baseline + new tests added
- [x] 6.2 Run `make demo` — confirm the elapsed field in the wide layout shows a sensible duration (not a time-since-last-write idle value)
