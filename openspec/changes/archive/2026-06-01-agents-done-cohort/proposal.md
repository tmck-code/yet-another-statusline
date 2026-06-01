## Why

The statusline currently hides each running subagent independently, 20 seconds after its transcript file stops being written to. This file-activity proxy has two failure modes: a healthy agent doing one slow operation (a long build or test run) writes nothing and vanishes mid-flight, and a finished agent's row keeps ticking its elapsed clock as if still alive. Treating a fan-out as one **cohort** — kept on screen until the whole wave is done, then retired together after a readable grace period — matches how the work is actually dispatched and read.

## What Changes

- Detect subagent completion from the transcript's `stop_reason: "end_turn"` signal (the "Done" beat) instead of inferring it from file-write staleness.
- Render a finished agent as a **dimmed** row: `▶` marker becomes `✓`, and elapsed **freezes** at its completion time (`end_ts − first_ts`) instead of ticking forever.
- Keep all cohort agents visible until the **last** one is Done, then retire the whole section together after a **20s** grace window.
- Scope the cohort to **the current turn**: agents spawned since the last user prompt, plus any pre-turn agent still actively writing. **Always show a running agent** regardless of age — the cutoff only retires finished/idle agents.
- Add a **`UserPromptSubmit` hook** (shipped in the plugin's `hooks/hooks.json`) that records the last user-prompt timestamp per session to a shared state file via atomic read-merge-write. The statusline reads it as the authoritative cohort lower-bound.
- Add a **60s janitor**: a cohort containing an agent that died without `end_turn` (interrupted/killed/errored) is swept after 60s of total silence, so the section always retires. The same 60s window is the **graceful fallback** when the prompt-marker file is absent or stale (fresh install, first prompt, older plugin version) — behaviour degrades to a recency window, never breaks.

## Capabilities

### New Capabilities
- `subagent-cohort`: Lifecycle, visibility, and rendering of the statusline's running-subagent section — Done detection via `end_turn`, turn-scoped cohort membership, cohort-level retirement with grace and janitor windows, and the dimmed/✓/frozen-elapsed treatment for finished agents.
- `prompt-boundary-hook`: A plugin-shipped `UserPromptSubmit` hook that records the last user-prompt timestamp per session to a shared state file (atomic read-merge-write), consumed by the statusline to scope the cohort to the current turn.

### Modified Capabilities
<!-- None. The existing statusline-config capability is unaffected; subagent rendering has no prior spec. -->

## Impact

- **Code**: `claude/statusline_command.py` — `RunningSubagent` (new `end_ts` field), `RunningSubagents._parse_transcript` (capture `end_turn` timestamp), `RunningSubagents.from_session` (stop per-agent stale-dropping; move to cohort-level visibility), a new cohort visibility method, and the three layout builders (`build_narrow`/`build_medium`/`build_wide`) plus `subagent_row` (dim/✓/frozen-elapsed branch).
- **Plugin**: `hooks/hooks.json` gains a `UserPromptSubmit` entry; a small hook script writes the shared per-session prompt-timestamp state file.
- **Constants**: cohort grace `20s`, janitor horizon / recency fallback `60s`, liveness window `30s` (widened from today's `STALE_SECONDS = 20`).
- **Tests/demo**: new `demo.py` scenarios (all-running, mixed running+done-dimmed, all-done-in-grace, dirty-janitor) and pytest coverage for `end_ts` parsing, cohort scoping, retirement timing, janitor sweep, fallback, and frozen-elapsed rendering.
- **Distribution**: no per-user `settings.json` edits required — the hook travels with the YAS plugin. Older installs without the hook degrade gracefully via the recency-window fallback.
