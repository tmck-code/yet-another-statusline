## Why

A finished subagent (observed with a "discovery" agent that ran before a batch
of implementation agents) kept showing as **active** in the statusline long
after it completed. The cause is a detection gap, not a visibility-policy gap:
`RunningSubagents._parse_transcript` dedupes assistant messages by `message.id`
and `continue`s on an already-seen id **before** it inspects `stop_reason`.
Streaming writes the same `message.id` several times — an early partial with
`stop_reason: null`, then a final write carrying `stop_reason: "end_turn"`. The
early partial enters the `seen` set, so the final end_turn write is skipped and
`end_ts` is never set. The agent is never marked Done, never receives the
dimmed Done treatment, and lingers looking busy.

## What Changes

- Harden Done detection so the `end_turn` signal is evaluated on **every**
  assistant+usage transcript line, independent of the `message.id` dedup. The
  dedup SHALL continue to guard token/usage accumulation only — never the
  terminal-state check.
- Capture `end_ts` from the end_turn line even when that message id was already
  counted for tokens by an earlier streaming partial.
- No change to the deliberate cohort behaviour: turn-scoped membership,
  retire-the-section-as-a-unit after the 20s grace, the 60s janitor sweep, and
  the dimmed visual treatment for finished members all stay exactly as
  specified. Once detection is correct, a finished member correctly dims instead
  of looking active.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `subagent-cohort`: the **Done detection via end_turn** requirement is
  strengthened — message-id dedup MUST NOT suppress the `end_turn` check, so a
  duplicated final-message id can no longer drop the Done signal.

## Impact

- `claude/yas/info/subagents.py` — `RunningSubagents._parse_transcript`: move the
  `stop_reason == 'end_turn'` / `end_ts` capture out from behind the
  `if mid in seen: continue` dedup guard; the dedup keeps gating only token
  accumulation.
- Tests: `test/test_running_subagents.py` (detection unit) and
  `test/test_cohort_visibility.py` (Done state armed) — add a fixture where the
  final end_turn message id duplicates an earlier streaming partial.
- No change to stdin payload, layout geometry, border math, or any other
  `subagent-cohort` requirement.

### Out of scope (deferred)

- The `subagentStatusLine` sidecar (writing CC's authoritative `status` field to
  a state file for YAS to read) is **explicitly deferred**. It is a gated
  fallback to revisit only if, after this fix, a finished agent is reproduced
  with no detectable `end_turn` in its transcript at all. It carries undocumented
  unknowns (the `tasks[].id` join target, the `status` enum, and whether a
  finished agent even still appears in the `tasks` feed) and adds a second hook
  surface — not justified while the terminal signal is recoverable from the
  transcript YAS already reads.
