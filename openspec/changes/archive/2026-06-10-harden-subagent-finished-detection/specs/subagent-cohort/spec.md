## MODIFIED Requirements

### Requirement: Done detection via end_turn

The statusline SHALL treat a subagent as **Done** when, and only when, its transcript jsonl contains an assistant message whose `message.stop_reason` equals `"end_turn"`. The timestamp of that line SHALL be captured as the subagent's `end_ts`. Transcript-write staleness SHALL NOT, on its own, mark a subagent Done.

The `end_turn` check SHALL be evaluated on every assistant message line that carries a usage block, **independent of message-id deduplication**. Deduplication by `message.id` SHALL guard only token/usage accumulation; it SHALL NOT cause a line bearing `stop_reason: "end_turn"` to be skipped. A streaming partial that wrote the same `message.id` earlier (with `stop_reason: null`) SHALL NOT suppress the terminal-state capture from the final write of that message.

#### Scenario: Clean finish marks Done

- **WHEN** a subagent transcript's final assistant message carries `stop_reason: "end_turn"`
- **THEN** the subagent is Done and its `end_ts` is the timestamp of that line

#### Scenario: Duplicated final-message id still marks Done

- **WHEN** the assistant message bearing `stop_reason: "end_turn"` shares its `message.id` with an earlier streaming partial line that had `stop_reason: null`
- **THEN** the dedup guard does not skip the terminal check, the subagent is marked Done, and `end_ts` is captured from the end_turn line

#### Scenario: Dedup still prevents double-counting tokens

- **WHEN** the same `message.id` appears across multiple transcript lines
- **THEN** that message's `usage` tokens are accumulated exactly once, while the `end_turn` check still runs on each line

#### Scenario: Silence does not mark Done

- **WHEN** a subagent transcript has had no writes for longer than the liveness window but contains no `end_turn`
- **THEN** the subagent is NOT marked Done (it is handled by the janitor sweep instead)

#### Scenario: Interrupted agent never emits end_turn

- **WHEN** a subagent was interrupted, killed, or errored and its transcript ends without `stop_reason: "end_turn"`
- **THEN** the subagent is never marked Done and never receives the Done visual treatment
