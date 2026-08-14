## ADDED Requirements

### Requirement: build requires both a recording and a live transcript

The `build` subcommand SHALL accept either a session id or a path to a
`.psv.gz` recording. It SHALL locate, and SHALL require, all of:

- the recording at `CLAUDE_DIR/yas/recordings/<session_id>.psv.gz` (or the given
  path),
- the session transcript at `CLAUDE_DIR/projects/<slug>/<session_id>.jsonl`,
- the subagent directory `CLAUDE_DIR/projects/<slug>/<session_id>/subagents/`,
  which MAY be absent or empty for a session that spawned no subagents.

If the recording is missing, or the transcript is missing, `build` SHALL exit
non-zero with an error naming the missing path, and SHALL NOT produce a partial
output file. Reconstructing a replay from a transcript alone SHALL NOT be
attempted: payload-only values such as `cost.total_cost_usd`,
`context_window.used_percentage`, and the terminal width have no transcript
equivalent.

#### Scenario: Both inputs present

- **WHEN** `build` is given a session id whose recording and transcript both exist
- **THEN** it writes the keyframe PSV to the `-o` path and exits zero

#### Scenario: Missing recording is fatal

- **WHEN** the session has a transcript but no recording
- **THEN** `build` exits non-zero, names the expected recording path, and writes
  no output file

#### Scenario: Missing transcript is fatal

- **WHEN** the recording exists but the transcript jsonl has been deleted
- **THEN** `build` exits non-zero, names the expected transcript path, and writes
  no output file

#### Scenario: No subagents is not an error

- **WHEN** the session has no `subagents/` directory
- **THEN** `build` succeeds and every frame's subagent blob is empty

#### Scenario: Recording path accepted directly

- **WHEN** `build` is given a filesystem path to a `.psv.gz` file
- **THEN** it derives the session id from the filename and resolves the
  transcript from it

### Requirement: Output is a self-contained keyframe PSV

`build` SHALL emit one row per recorded tick, each row a **full snapshot** of
everything needed to render that frame. No row SHALL depend on any preceding row,
so a consumer SHALL be able to seek to any row and render it directly. The
emitted file SHALL be plain text (not compressed), pipe-separated, with a header
row naming every column, and SHALL be sufficient on its own: after `build`,
neither the recording nor the transcript SHALL be needed to play or export.

#### Scenario: One row per tick

- **WHEN** a recording holds 120 ticks
- **THEN** the output has a header row plus 120 data rows, in ascending timestamp
  order

#### Scenario: Rows are independent

- **WHEN** any single data row is read in isolation together with the header
- **THEN** it carries every field needed to render that frame

#### Scenario: Output is self-contained

- **WHEN** the recording and the transcript are deleted after `build`
- **THEN** `play` and `export` still work from the built file alone

### Requirement: Scalar payload fields are flattened to dotted column names

Every scalar leaf of the recorded payload SHALL become its own column, named by
its dotted path through the payload object — for example
`context_window.current_usage.input_tokens`, `cost.total_cost_usd`, `model.id`,
`exceeds_200k_tokens`. The column set SHALL be **derived** from the payloads
present in the recording, not hand-enumerated, so that a payload gaining a field
gains a column without a code change. A field absent from a given tick SHALL
render as an empty cell and SHALL be restored as absent, not as an empty string,
when the row is rebuilt into a payload. Values SHALL be preserved verbatim from
the recording, since they are what yas was actually given.

#### Scenario: Nested scalars get dotted names

- **WHEN** a payload contains `{"cost": {"total_cost_usd": 1.25}}`
- **THEN** the output has a `cost.total_cost_usd` column holding `1.25`

#### Scenario: Column set follows the data

- **WHEN** the recorded payloads contain a field the tool has no knowledge of
- **THEN** that field still appears as a dotted column

#### Scenario: Late-appearing field is empty earlier

- **WHEN** a field appears only from tick 50 onward
- **THEN** rows 1-49 have an empty cell in that column, and rebuilding those rows
  yields payloads in which the key is absent

#### Scenario: Payload values are verbatim

- **WHEN** a row is rebuilt into a payload object
- **THEN** its scalar values equal those in the corresponding recorded line

### Requirement: Non-scalar state is carried in JSON-blob columns

The output SHALL carry the following additional columns, each holding a minified
JSON document, alongside the flattened scalars:

- `tasks` — the task checklist as of the tick,
- `subagents` — the subagent cohort state as of the tick, including per-agent
  type, description, parent, tokens, model, lifecycle status, and last activity,
- `tool_counts` — per-tool use counts and line counts as of the tick,
- `rate_series` — the recent token-rate samples for the tick's window,
- and the scalar columns `ts` (real epoch timestamp), `width` (recorded terminal
  width), and `git_branch`.

`git_branch` SHALL be taken from the `gitBranch` field of the transcript record
envelope, because the payload does not carry it.

#### Scenario: Blob columns are present

- **WHEN** the output header is read
- **THEN** it contains `ts`, `width`, `git_branch`, `tasks`, `subagents`,
  `tool_counts`, and `rate_series`

#### Scenario: Blobs are valid minified JSON

- **WHEN** any blob cell is parsed as JSON
- **THEN** it parses successfully and contains no literal newline or unescaped
  separator that would break the row

#### Scenario: Branch comes from the transcript

- **WHEN** the transcript records carry `gitBranch` of `feature/x`
- **THEN** frames at those times have `git_branch` of `feature/x`

### Requirement: Transcript-derived state is time-sliced to each tick

For a tick at time *t*, every blob column SHALL be computed considering only
transcript and subagent records whose `timestamp` is at or before *t* — the
records that existed on disk when yas rendered that tick. Task state SHALL be
derived by replaying the TodoWrite tool calls up to *t*; tool counts SHALL be
windowed to the most recent `/clear` marker at or before *t*; subagent state
SHALL be derived from the `agent-*.meta.json` files and the `<task-notification>`
records up to *t*. The transcript and each subagent file SHALL be walked **once**
in a single streaming pass over the sorted tick timestamps, not once per tick.

#### Scenario: Later records do not leak backwards

- **WHEN** a task is marked completed at time *t*+60
- **THEN** the frame at *t* shows that task as still in progress

#### Scenario: Clear resets the tool-count window

- **WHEN** a `/clear` occurs at time *c*
- **THEN** frames after *c* count only tool uses at or after *c*, and frames
  before *c* are unaffected

#### Scenario: Subagent lifecycle follows notifications

- **WHEN** a subagent's completion notification is stamped at time *k*
- **THEN** frames before *k* show it running and frames at or after *k* show it
  completed

#### Scenario: Single pass per file

- **WHEN** `build` runs over a recording of N ticks
- **THEN** the transcript and each subagent file are opened and read once, not N
  times

### Requirement: Token-rate series is derived from consecutive keyframes

The `rate_series` column SHALL be computed from the cumulative token totals of
consecutive keyframes — the difference in totals over the elapsed real time
between ticks — and SHALL NOT read the live token-rate log, which is not part of
the recording. The first frame SHALL carry an empty or zero-rate series, since it
has no predecessor.

#### Scenario: Rate follows the token deltas

- **WHEN** consecutive frames 10 seconds apart show cumulative totals rising by
  5,000 tokens
- **THEN** the later frame's rate series carries a sample of 500 tokens per second

#### Scenario: First frame has no rate

- **WHEN** the first frame is built
- **THEN** its rate series is empty or zero

#### Scenario: Live rate log is not consulted

- **WHEN** `build` runs
- **THEN** it does not read `CLAUDE_DIR/statusline-token-rate.log`
