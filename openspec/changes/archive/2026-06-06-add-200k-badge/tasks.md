<!-- AGENT INSTRUCTIONS: Mark each subtask done with TaskUpdate (status: completed) the
     moment it is finished — before starting the next task. This keeps progress visible
     to observers in real time. Tasks 4 and 5 are independent and MAY be delegated to
     parallel subagents; each subagent must mark its own subtask done immediately. -->

## 1. Understand current code

- [x] 1.1 Read `claude/yas/renderer.py` lines 969–1020 (`context_line`, `context_line_compact`) to understand how `available` and `bar_w` are computed
- [x] 1.2 Read `claude/yas/constants.py` to check whether an amber/yellow warning colour constant already exists (e.g. `CLR_YELLOW`, `CLR_AMBER`, `CLR_ORANGE`); note its name or confirm it must be added
- [x] 1.3 Read `claude/yas/session.py` to confirm `SessionInfo.exceeds_200k_tokens` field name and type
- [x] 1.4 Run `make test` and record the baseline pass count

## 2. Add colour constant (if absent)

- [x] 2.1 If no suitable amber/yellow constant exists in `constants.py`, add one: `CLR_AMBER = '\x1b[33m'` (standard ANSI yellow, readable on dark terminals); follow the existing `CLR_*` naming and grouping conventions

## 3. Add badge to context_line (wide/medium)

- [x] 3.1 Add `exceeds_200k: bool = False` as a keyword argument to `context_line()`
- [x] 3.2 Compute `badge = f'{CLR_AMBER}!200K{RESET} ' if exceeds_200k else ''` and `badge_w = 6 if exceeds_200k else 0`
- [x] 3.3 Subtract `badge_w` from `bar_w` (before the `filled = int(fill_ratio * bar_w)` line); floor `bar_w` at 0
- [x] 3.4 Prepend `badge` to the returned string

## 4. Add badge to context_line_compact (narrow)

- [x] 4.1 Apply the same changes (tasks 3.1–3.4) to `context_line_compact()`, keeping the compact variant's existing structure intact

## 5. Thread exceeds_200k into callers

- [x] 5.1 In `layout.py` (or wherever `context_line` / `context_line_compact` are called), pass `exceeds_200k=view.session.exceeds_200k_tokens` (or the equivalent `SessionInfo` field) to both helpers

## 6. Tests (can be done in parallel with step 7)

- [x] 6.1 In `test/test_context_line.py` (or create it): add scenario — `exceeds_200k_tokens=True` → returned string contains `!200K`
- [x] 6.2 Add scenario — `exceeds_200k_tokens=False` → returned string does NOT contain `!200K`
- [x] 6.3 Add scenario — `exceeds_200k_tokens=True`, `available=60` → bar fills at most 54 columns (badge deduction applied)
- [x] 6.4 Add scenario — badge rendered in amber colour (assert `CLR_AMBER` or `\x1b[33m` appears before `!200K`)

## 7. Re-baseline snapshots (can be done in parallel with step 6)

- [x] 7.1 Run `make demo/img` with a payload where `exceeds_200k_tokens=true`; inspect the context row; update any affected snapshot baselines

## 8. Verify

- [x] 8.1 Run `make test` — must be green with count ≥ baseline + new tests added
- [x] 8.2 Run `make demo` — confirm normal sessions show no badge; if possible pass a modified session JSON with `exceeds_200k_tokens: true` to confirm badge appearance: `COLUMNS=160 uv run python claude/statusline_command.py < ops/session-info-example.json`
