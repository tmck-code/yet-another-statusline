## 1. Harden the detection in the data layer

- [ ] 1.1 In `RunningSubagents._parse_transcript` (`claude/yas/info/subagents.py`), restructure the per-line handling so the `stop_reason == 'end_turn'` / `end_ts` capture runs for every assistant+usage line, independent of the `if mid in seen: continue` dedup guard.
- [ ] 1.2 Keep token/usage accumulation and `model`/`seen` bookkeeping behind the dedup guard so a duplicated `message.id` is still counted exactly once.
- [ ] 1.3 Preserve last-write-wins for `end_ts` (a later end_turn line overwrites an earlier one; non-terminal lines never touch `end_ts`).

## 2. Tests

- [ ] 2.1 In `test/test_running_subagents.py`, add a fixture transcript where the final `stop_reason: "end_turn"` message shares its `message.id` with an earlier streaming partial (`stop_reason: null`); assert `end_ts > 0` (Done detected).
- [ ] 2.2 Assert that the same duplicated-id transcript accumulates `usage` tokens exactly once (no double-count regression).
- [ ] 2.3 In `test/test_cohort_visibility.py`, add a case asserting the duplicated-final-id agent reaches the Done state and is eligible for the dimmed treatment / cohort grace, rather than appearing active.
- [ ] 2.4 Confirm existing detection scenarios still hold: clean single-write end_turn marks Done; an interrupted transcript with no end_turn stays not-Done.

## 3. Verification

- [ ] 3.1 Run `make test` — green, baseline + new tests.
- [ ] 3.2 Run `make demo` — eyeball a subagent that finishes mid-run; confirm it transitions to the dimmed Done treatment instead of lingering as active, and the box stays aligned.
