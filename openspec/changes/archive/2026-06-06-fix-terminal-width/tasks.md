<!-- AGENT INSTRUCTIONS: Mark each subtask done with TaskUpdate (status: completed) the
     moment it is finished — before starting the next task. This keeps progress visible
     to observers in real time. Tasks 3 and 4 are independent and MAY be delegated to
     parallel subagents; each subagent must mark its own subtask done immediately. -->

## 1. Understand current code

- [x] 1.1 Read `claude/yas/render/text.py` lines 1–55 (`terminal_width()` function) to confirm the current probe order and the tmux `subprocess.run` call signature
- [x] 1.2 Run `make test` and record the baseline pass count

## 2. Fix probe order and tmux timeout

- [x] 2.1 Move the `COLUMNS` env-var block (currently the third probe) to be the **first** check in `terminal_width()`, before the tmux subprocess block
- [x] 2.2 Add `timeout=0.2` to the `subprocess.run(["tmux", ...])` call
- [x] 2.3 Add `subprocess.TimeoutExpired` to the existing `except` tuple on the tmux block so a timeout is caught and the function falls through to the next source

## 3. Tests (can be done in parallel with step 4)

- [x] 3.1 In `test/test_terminal_width.py` (or the closest existing test file): add scenario — `COLUMNS=160` set → `terminal_width()` returns `160` without calling `subprocess.run`
- [x] 3.2 Add scenario — `COLUMNS` not set, tmux returns `120` within timeout → returns `120`
- [x] 3.3 Add scenario — `COLUMNS` not set, tmux `subprocess.run` raises `TimeoutExpired` → function continues to next source (does not raise)
- [x] 3.4 Add scenario — `COLUMNS=0` → function skips to next source

## 4. Review other tests (can be done in parallel with step 3)

- [x] 4.1 Search existing tests for any that mock `subprocess.run` for the tmux probe or patch `os.environ['COLUMNS']`; update them if the probe-order change breaks their assumptions

## 5. Verify

- [x] 5.1 Run `make test` — must be green with count ≥ baseline + new tests added
- [x] 5.2 Manually confirm: `COLUMNS=99 uv run python claude/statusline_command.py < ops/session-info-example.json` produces a 99-column render
