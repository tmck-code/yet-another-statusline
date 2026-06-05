<!-- AGENT INSTRUCTIONS: Mark each subtask done with TaskUpdate (status: completed) the
     moment it is finished — before starting the next task. This keeps progress visible
     to observers in real time. Tasks 3 and 4 are independent and MAY be delegated to
     parallel subagents; each subagent must mark its own subtask done immediately. -->

## 1. Understand current code

- [x] 1.1 Read `claude/mon/discovery.py` lines 1–55 to confirm both hardcoded `Path.home() / '.claude'` occurrences and verify `CLAUDE_DIR` is not already imported there
- [x] 1.2 Read `claude/yas/constants.py` to confirm the name and import path for `CLAUDE_DIR`
- [x] 1.3 Run `make test` and record the baseline pass count

## 2. Apply the fix (two-line change)

- [x] 2.1 Add `from yas.constants import CLAUDE_DIR` to the imports in `claude/mon/discovery.py`
- [x] 2.2 Replace `Path.home() / '.claude' / 'projects'` (the default argument on the projects-root parameter, line ~21) with `CLAUDE_DIR / 'projects'`
- [x] 2.3 Replace `Path.home() / '.claude' / 'statusline-output'` (the default argument on the payloads-root parameter, line ~43) with `CLAUDE_DIR / 'statusline-output'`

## 3. Tests (can be done in parallel with step 4)

- [x] 3.1 In `test/test_mon_discovery.py`: add a scenario that sets `CLAUDE_CONFIG_DIR` to a temp directory and confirms the discovery functions look there rather than `~/.claude`
- [x] 3.2 Confirm the existing discovery tests still pass (they should be unaffected if they use the `tmp_home` fixture or pass explicit paths)

## 4. Grep check (can be done in parallel with step 3)

- [x] 4.1 Run `grep -rn "Path.home.*\.claude" claude/mon/` and confirm no remaining hardcoded occurrences after the fix

## 5. Verify

- [x] 5.1 Run `make test` — must be green with count ≥ baseline + new tests added
