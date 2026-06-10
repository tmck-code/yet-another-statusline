## Context

`RunningSubagents._parse_transcript` (`claude/yas/info/subagents.py`) walks a
subagent `.jsonl` and, for each assistant line carrying a `usage` block,
accumulates tokens and records terminal state. To avoid double-counting tokens
when the same assistant message is written multiple times during streaming, it
dedupes on `message.id`:

```python
mid = msg.get('id')
if not mid or mid in seen:
    continue          # <-- skips EVERYTHING below, including end_turn capture
seen.add(mid)
...                   # token accumulation
if msg.get('stop_reason') == 'end_turn':
    end_ts = _parse_iso_to_epoch(d.get('timestamp', ''))
```

Streaming emits the same `message.id` several times: early partials carry
`stop_reason: null`; the final write carries `stop_reason: "end_turn"`. The
early partial enters `seen` first, so the final end_turn write hits
`mid in seen` and is `continue`d — the `end_ts` capture never runs. The agent is
never marked Done, never dims, and lingers looking active. This was observed
with a discovery agent that ran before a batch of implementation agents.

The dedup is correct for its real purpose (token accumulation must happen once).
The defect is that it also gates the terminal-state check, which must run on
every line.

## Goals / Non-Goals

**Goals:**
- Capture `end_ts` from a `stop_reason: "end_turn"` line even when that
  `message.id` was already counted by an earlier streaming partial.
- Keep token/usage accumulation deduped exactly once per `message.id`.
- Leave every other `subagent-cohort` requirement untouched: turn-scoped
  membership, retire-as-a-unit + 20s grace, 60s janitor sweep, and the dimmed
  Done treatment.

**Non-Goals:**
- Changing cohort retirement policy (no per-member individual retirement; the
  section still retires as a unit — once detection is fixed, the finished member
  correctly dims while siblings run, which is the intended behaviour).
- Any `subagentStatusLine` sidecar / CC `status` field integration (deferred;
  see proposal Out of scope).
- Changes to token math, duration, `first_timestamp`, `model`, or
  `last_activity` selection.

## Decisions

- **Lift the terminal-state check out of the dedup branch.** Evaluate
  `stop_reason == 'end_turn'` (and capture `end_ts`) for every assistant+usage
  line, then `continue` the *token accumulation* only when `mid in seen`.
  Concretely, restructure so the end_turn capture runs before — or regardless of
  — the `if mid in seen: continue` guard, while token sums and `model`/`seen`
  bookkeeping stay behind it.

  *Alternative considered:* dedupe end_turn by remembering whether `end_ts` was
  already set and only updating on the latest timestamp. Rejected as redundant —
  re-running the cheap check on a duplicate line is harmless and yields the same
  `end_ts`; the simpler structural fix has no extra state.

  *Alternative considered:* the `subagentStatusLine` sidecar as the source of
  truth. Rejected for this change — the terminal signal is recoverable from the
  transcript YAS already reads; the sidecar adds a second hook surface and three
  undocumented unknowns. Deferred as a gated fallback.

- **`end_ts` value on duplicates.** When multiple end_turn-bearing lines share an
  id (rare), the **last** one wins, matching the existing "timestamp of that
  line" semantics and keeping `end_ts` monotonic with the final write.

## Risks / Trade-offs

- **Re-evaluating end_turn on every duplicate line** → negligible cost: a dict
  `.get` and a string compare per assistant line; transcripts are small and read
  once per render.
- **A mid-stream partial that transiently reports `end_turn`** → not observed in
  practice (only the final write carries it), and the last-write-wins rule means
  a later non-terminal line cannot un-set `end_ts` because non-terminal lines
  never touch `end_ts`. Accepted.
- **Token double-count regression** → guarded by an explicit test asserting a
  duplicated id accumulates `usage` exactly once while still capturing `end_ts`.
