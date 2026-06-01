## Context

The statusline renders running subagents by scanning `~/.claude/projects/<slug>/<session>/subagents/*.meta.json`, pairing each with its sibling `.jsonl` transcript, and dropping any agent whose transcript hasn't been written for `STALE_SECONDS = 20` (`RunningSubagents.from_session`, `claude/statusline_command.py:1240`). The render is **stateless**: every invocation re-derives everything from disk. Rows are built by `subagent_row` (`:2420`) and placed by three layout builders (`build_narrow`/`build_medium`/`build_wide`, ~`:2895`/`:2943`/`:3003`).

Empirically, `stop_reason: "end_turn"` appears on the final assistant line in 78% of real subagent transcripts (117/150 sampled) and is reliably the last line when present (115/117). The other 22% — interrupted, killed, or errored agents — never emit it. This asymmetry is the central design constraint.

This repo is itself a Claude Code **plugin** (`.claude-plugin/`, `hooks/hooks.json` currently `{}`), so it can ship hooks that travel with installation.

## Goals / Non-Goals

**Goals:**
- Replace per-agent file-staleness hiding with cohort-level retirement driven by a real completion signal.
- Keep a fan-out's full roster on screen until the whole wave is Done, then retire together after a readable 20s grace.
- Make a finished row visually honest: `✓`, dimmed, frozen elapsed.
- Scope the cohort to the current turn so a new wave doesn't drag in old agents.
- Never break rendering, and degrade gracefully where the `end_turn` signal or the prompt marker is absent.

**Non-Goals:**
- Migrating Done-detection onto `SubagentStart`/`SubagentStop` hooks. Those are richer (they carry `agent_id`/`last_assistant_message`) but flagged underdocumented (GitHub #19170, #16424); this change keeps Done-detection stateless and transcript-based, and uses a hook only for the well-documented prompt boundary.
- Changing the per-row metric cluster (t/m, share %, token figures) or the wide/narrow layout breakpoints.
- Any change to the `statusline-config` capability.

## Decisions

### Done = `end_turn` only; staleness is a janitor, not a Done signal
A subagent is Done strictly when `end_turn` is seen. Staleness never paints the Done visual. This guarantees the `✓`/dim/frozen-elapsed state is **never a lie** — a healthy agent doing one slow operation (a long build) goes silent but is never falsely checked off, and a retiring section never resurrects.
- *Alternative — staleness counts as Done (20s window):* simplest, mirrors today, but a `✓` could un-check itself and a slow-but-alive agent would flicker. Rejected for honesty.
- *Alternative — widen liveness to 45–60s and let staleness mean Done:* a compromise that still flickers on genuinely slow ops and lingers dead agents. Rejected.

### Cohort = this turn's agents, with a live-straggler exception
Membership = `first_timestamp ≥ last_prompt_ts` **OR** still actively writing (within the liveness window). A running agent is always shown; the cutoff only retires finished/idle agents. This is sharper than a pure recency window: a new prompt cleanly defines a new cohort, but a long-running agent spawned in the prior turn is never yanked off-screen mid-flight.
- *Alternative — strict turn boundary (`first_timestamp ≥ last_prompt_ts` only):* cleanest definition, but hides an actively-running pre-turn agent the instant a new prompt lands. Rejected.
- *Alternative — pure recency window / burst clustering:* no prompt parsing needed, but "turn" becomes "recent activity" and a slow drip of one-off agents confuses clustering. Kept as the *fallback*, not the primary.

### Last-prompt timestamp comes from a hook, not transcript parsing
The main transcript marks real prompts, slash-command expansions, `<local-command-caveat>` blocks, `tool_result` payloads, sidechain and `isMeta` lines all as `type: "user"`. Distinguishing a genuine prompt is an unreliable heuristic. A `UserPromptSubmit` hook receives `session_id` + can write files (well-documented, 30s timeout), giving an **authoritative** boundary. It ships in the plugin's `hooks/hooks.json` (no `settings.json` edits) and writes a single shared `session_id → timestamp` map via atomic read-merge-write (temp file + rename).
- *Alternative — parse the transcript for the last prompt:* fragile against the masquerading-user-line problem above. Rejected as primary; the recency-window fallback covers the no-hook case.
- *Alternative — per-session marker files instead of one shared map:* avoids all concurrency, but scatters many small files. The shared-map + atomic-rename pattern was chosen; per-session files remain a viable simplification if concurrency proves troublesome.

### Three time constants
| Constant | Value | Role |
|---|---|---|
| Cohort grace | 20s | visible time after the last member's `end_ts` before a clean section retires |
| Janitor horizon | 60s | total-silence threshold to sweep a dirty cohort; also the no-hook recency fallback window |
| Liveness window | 30s | silence threshold for "idle" vs "still writing" (straggler-keep, running-vs-finished); widened from today's `STALE_SECONDS = 20` |

Grace and janitor are deliberately separate: a clean finish retires fast (20s after the last `end_turn`); a dirty cohort needs the longer 60s backstop. Liveness was widened to 30s so a moderately slow op isn't misread as idle.

### Frozen elapsed needs one new field
`_parse_transcript` already walks every line; it additionally captures `end_ts` (the `end_turn` line's timestamp). `RunningSubagent` gains `end_ts: float` — dual purpose: Done flag (`end_ts > 0`) and the basis for frozen elapsed (`end_ts − first_timestamp`). No second pass.

### Visibility moves from per-agent to cohort-level
`from_session` stops `continue`-ing past stale agents (today's `:1273`). Instead it returns the full candidate set, and a new method on `RunningSubagents` (e.g. `visible(now, last_prompt_ts)`) computes membership + the clean-retire-vs-janitor decision over the whole set. The three layout builders ask the cohort "are you visible?" instead of `if subagents.subagents`.

## Risks / Trade-offs

- **Dirty cohort lingers up to 60s looking live** → Accepted. Only the 22% no-`end_turn` case, and only when a member dies without writing again; the janitor still guarantees eventual removal. Chosen over a faster sweep that would risk killing genuinely-slow agents.
- **`end_turn` schema could change** → Mitigation: parsing is defensive (`stop_reason == "end_turn"` guarded by try/except, same as existing transcript parsing); absence simply routes an agent to the janitor path, never crashes.
- **Hook absent (older install / fresh session / first prompt)** → Mitigation: recency-window fallback (60s) keeps the feature working, close to today's behaviour, with no error.
- **Shared state-file concurrency** → Mitigation: read-merge-write with atomic rename preserves sibling entries; readers always see a complete map. Per-session files remain a fallback simplification.
- **`SubagentStop` would be a cleaner Done signal** → Deferred, not adopted: underdocumented today. The design leaves room to migrate Done-detection onto it later without disturbing the cohort/visibility logic.

## Migration Plan

1. Land the statusline changes (`end_ts` field, cohort visibility method, `subagent_row` Done branch, layout builder call-site updates) behind no flag — behaviour is strictly additive and degrades to the recency window if the hook is absent.
2. Add the `UserPromptSubmit` hook to `hooks/hooks.json` and its small writer script.
3. Existing installs that update the plugin gain the hook on next prompt; until then they run the fallback path. No rollback coordination needed — removing the hook simply reverts to the recency window.

## Open Questions

- Liveness window pinned at **30s** (smaller end of the "30–45s" range chosen during design). Revisit if moderately slow ops still read as idle in practice.
- Exact path/name of the shared state file (e.g. `~/.claude/yas-last-prompt.json`) to be finalised during implementation.
