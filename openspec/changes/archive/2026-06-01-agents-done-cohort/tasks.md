# Tasks — agents-done-cohort

> **Fan-out execution.** These tasks are grouped so independent groups can be
> dispatched to multiple workers (main agent or subagents) in parallel. Each
> group's header notes its dependencies and whether it is parallel-safe.
>
> **⚠ MARK SUBTASKS DONE THE INSTANT THEY ARE DONE.** Every worker — the main
> agent and every subagent — MUST flip its checkbox from `- [ ]` to `- [x]` in
> this file *immediately* upon completing each subtask, before moving to the
> next one. Do not batch updates, do not wait until a group is finished, do not
> defer to the end. The apply phase and any observer read this file to track
> live progress; a delayed update makes the spec's progress unobservable and can
> cause two workers to collide on the same subtask. If a subtask is partially
> done, leave it unchecked. One completed subtask → one immediate checkbox flip.

## 1. Foundation — data model & constants

> Depends on: nothing. Do this first; groups 2–4 build on it. Single worker.

- [x] 1.1 Add `end_ts: float = 0.0` field to the `RunningSubagent` dataclass (`claude/statusline_command.py:1221`), documented as the `end_turn` line timestamp and Done flag (`end_ts > 0` ⟺ Done)
- [x] 1.2 Define the three time constants near `RunningSubagents`: cohort grace `20s`, janitor horizon `60s`, liveness window `30s` (widening the existing `STALE_SECONDS = 20`); name them clearly and reference their roles
- [x] 1.3 Decide and document the shared state-file path constant (e.g. `~/.claude/yas-last-prompt.json`) used by both the hook writer and the statusline reader

## 2. Done detection — transcript parsing

> Depends on: group 1. Parallel-safe with groups 3 and 5 once group 1 lands.

- [x] 2.1 In `RunningSubagents._parse_transcript` (`:1296`), capture `end_ts`: when a line is an assistant message with `message.stop_reason == "end_turn"`, record that line's timestamp (defensive parse, mirror existing try/except style)
- [x] 2.2 Thread `end_ts` through `_parse_transcript`'s return tuple and into the `RunningSubagent(...)` construction in `from_session` (`:1279`)
- [x] 2.3 Unit test: a transcript with a trailing `end_turn` yields `end_ts > 0` equal to that line's epoch; a transcript without `end_turn` yields `end_ts == 0.0`

## 3. Cohort membership & retirement logic

> Depends on: group 1 (and reads `end_ts` from group 2). Core logic — single worker.

- [x] 3.1 Stop dropping stale agents per-agent in `from_session`: remove the `now - mtime > STALE_SECONDS: continue` filter (`:1272`) so the full candidate set is returned (still capturing each agent's transcript mtime for liveness/janitor decisions)
- [x] 3.2 Add a `RunningSubagents` method, e.g. `visible(now, last_prompt_ts) -> list[RunningSubagent]`, computing turn-scoped membership: `first_timestamp >= last_prompt_ts` OR written within the liveness window (still-writing straggler); a running agent is always included
- [x] 3.3 In that method, implement cohort retirement: if every member is Done, hide the section once `now - max(end_ts) > 20s` (cohort grace); otherwise apply the 60s janitor — hide when no member's transcript has been written for 60s
- [x] 3.4 Implement the no-marker fallback: when `last_prompt_ts` is absent, scope membership by the 60s recency window instead of by turn
- [x] 3.5 Unit tests: agent-this-turn included; pre-turn-still-writing kept; old finished agent excluded; running-agent-always-shown; clean retire at 20s; janitor sweep at 60s; recency fallback when no marker

## 4. Prompt-boundary hook (independent track)

> Depends on: group 1.3 (state-file path) only. Parallel-safe with groups 2–3.

- [x] 4.1 Add a `UserPromptSubmit` entry to the plugin's `hooks/hooks.json` (currently `{}`), wiring a command hook
- [x] 4.2 Write the hook script: read `session_id` from stdin JSON, read the existing `session_id → timestamp` map, update only this session's entry, write to a temp file and atomically rename into place
- [x] 4.3 Make the hook robust: missing/corrupt state file → start from an empty map; never error out of the hook
- [x] 4.4 In the statusline, read the current session's timestamp from the state file (missing/unreadable → return `None` so group 3.4's fallback engages); never raise
- [x] 4.5 Unit tests: two-session concurrent write preserves both entries; truncated/invalid JSON read returns `None` and does not raise

## 5. Rendering — Done row treatment

> Depends on: group 1 (reads `end_ts`). Parallel-safe with groups 2–4.

- [x] 5.1 In `subagent_row` (`:2420`), branch on Done (`sub.end_ts > 0`): compute frozen `dur = end_ts - first_timestamp` instead of `now - first_timestamp`
- [x] 5.2 Swap the leading marker from `▶` (`GLYPH_SUBAGENT_ROW`) to `✓` on Done rows; choose/define the checkmark glyph
- [x] 5.3 Apply dimmed styling to Done rows, overriding the rainbow marker colour (`rainbow_at`) and the per-field colours; keep running rows byte-for-byte unchanged
- [x] 5.4 Verify both wide (>100 col) and narrow (≤100 col) layouts render the Done treatment correctly
- [x] 5.5 Unit tests: Done row shows `✓` + frozen elapsed; running row unchanged; elapsed does not increase across two renders of a Done agent

## 6. Layout integration

> Depends on: groups 3 and 5. Single worker (touches all three builders).

- [x] 6.1 Update `build_narrow` (`~:2895`), `build_medium` (`~:2943`), `build_wide` (`~:3003`) to call the cohort `visible(...)` method and gate the section on its result instead of `if subagents.subagents`
- [x] 6.2 Pass the last-prompt timestamp (from group 4.4) into the visibility call at each site
- [x] 6.3 Confirm the section separator / spacing rows only render when at least one member is visible

## 7. Demo scenarios & verification

> Depends on: groups 3, 5, 6. Do last.

- [x] 7.1 Add `demo.py` scenario: all-running cohort (no Done rows)
- [x] 7.2 Add `demo.py` scenario: mixed running + Done-dimmed members
- [x] 7.3 Add `demo.py` scenario: all-done within the 20s grace window
- [x] 7.4 Add `demo.py` scenario: dirty cohort awaiting the 60s janitor
- [x] 7.5 Run `make demo` and visually confirm the four scenarios render as designed (✓, dimming, frozen elapsed, spacing)
- [x] 7.6 Run `make test` (full pytest suite) and confirm green, including the existing `test_running_subagents.py` / `test_subagent_rows.py` / `test_layout_subagent_rows.py` (update assertions that encoded the old per-agent 20s-stale-drop behaviour)
- [x] 7.7 Update `CONTEXT.md` "Running Subagent" language to describe cohort retirement, the `✓`/dim/frozen-elapsed Done state, and the three time constants
