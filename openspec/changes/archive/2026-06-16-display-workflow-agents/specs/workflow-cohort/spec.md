## ADDED Requirements

### Requirement: Workflow run detection via filesystem

The statusline SHALL detect a workflow run by the existence of a `subagents/workflows/<runId>/` directory under the session's project directory. A run SHALL be discovered the instant any agent transcript appears in that directory, independently of whether the session-level `workflows/<runId>.json` exists yet. Each `agent-<id>.jsonl` in the run directory SHALL be parsed with the same transcript parser used for ordinary subagents to obtain tokens, the activity snippet, `first_timestamp`, `mtime`, and `end_ts`.

#### Scenario: Run discovered before its JSON is written

- **WHEN** `subagents/workflows/<runId>/` contains at least one `agent-*.jsonl` but no `workflows/<runId>.json` exists yet
- **THEN** the run is detected and each agent is parsed from its transcript

#### Scenario: Agent identity comes from the transcript filename

- **WHEN** a workflow agent transcript is named `agent-<id>.jsonl`
- **THEN** its `agentId` is `<id>`, used to match against the run JSON's `workflowProgress` entries

#### Scenario: Non-workflow subagents are unaffected

- **WHEN** the session has both ordinary `subagents/agent-*.jsonl` files and `subagents/workflows/<runId>/agent-*.jsonl` files
- **THEN** the ordinary subagents remain in the normal cohort and only the nested agents are grouped into workflow runs

### Requirement: Run enrichment from the run JSON

The statusline SHALL read `workflows/<runId>.json` opportunistically to enrich a detected run. When present and parseable, the run's display name SHALL be its `workflowName`, each agent's label SHALL be the `label` of the matching `agentId` entry in `workflowProgress`, and the current phase SHALL be derived from the run's phase progress. The run JSON SHALL NOT be required for detection and SHALL NOT, on its own, mark a run live or retired.

#### Scenario: Name and labels taken from the JSON

- **WHEN** `workflows/<runId>.json` exists with a `workflowName` and `workflowProgress` mapping agentIds to labels
- **THEN** the run header shows `workflowName` and each agent row shows its mapped label

#### Scenario: Malformed JSON degrades to fallback

- **WHEN** `workflows/<runId>.json` is missing, empty, or fails to parse
- **THEN** detection still succeeds and the run renders using fallback identity (see Fallback identity requirement)

### Requirement: Fallback identity without the run JSON

When the run JSON does not supply a name or a label for an agent, the statusline SHALL fall back deterministically. The run header name SHALL fall back to the `runId`. An agent's label SHALL fall back to the first non-empty line of the first user message in its transcript, sanitized for untrusted input and middle-ellipsised to the available width. The phase SHALL be omitted from the header when no phase is available.

#### Scenario: Header falls back to runId

- **WHEN** a run has no `workflowName` available
- **THEN** the run header shows the `runId` (e.g. `wf_d8212a1d-34a`)

#### Scenario: Label falls back to the prompt line

- **WHEN** an agent has no mapped label in `workflowProgress`
- **THEN** its row label is the sanitized first non-empty line of its first user message, middle-ellipsised to fit

#### Scenario: Phase omitted when unknown

- **WHEN** no current phase can be derived for a run
- **THEN** the run header renders without a phase segment

### Requirement: Done detection reused from the subagent parser

A workflow agent SHALL be treated as **Done** under the same rule as ordinary subagents: when, and only when, its transcript contains an assistant message whose `message.stop_reason` equals `"end_turn"`, with that line's timestamp captured as `end_ts`. The run's summary count of completed agents SHALL be the number of agents with `end_ts > 0`.

#### Scenario: Completed agent counts toward the summary

- **WHEN** an agent transcript's final assistant message carries `stop_reason: "end_turn"`
- **THEN** that agent is Done and is included in the summary's `M done` count

#### Scenario: Still-running agent is not counted Done

- **WHEN** an agent transcript contains no `end_turn`
- **THEN** that agent is not Done and is excluded from the `M done` count

### Requirement: Run-scoped liveness and retirement

The statusline SHALL apply a workflow-sized liveness window that is independent of, and longer than, the subagent cohort's windows, so a run survives between-phase lulls. A run SHALL remain visible while any of its agents has a transcript `mtime` within the workflow liveness window (default 120 seconds), OR while its run JSON reports a non-terminal status. A run SHALL retire once it is settled — its run JSON reports a terminal status (or, in the filesystem-only case, every agent has `end_ts > 0`) AND its most recently written agent transcript is older than a grace window.

#### Scenario: Run survives a between-phase lull

- **WHEN** all of a run's currently-spawned agents have finished but the run is between phases and the most recent transcript write is within the workflow liveness window
- **THEN** the run remains visible

#### Scenario: Settled run retires after grace

- **WHEN** a run is terminal (JSON terminal status, or all agents `end_ts > 0`) AND its newest agent transcript `mtime` is older than the grace window
- **THEN** the run is no longer visible

#### Scenario: Stale leftover run directory is not shown

- **WHEN** a `subagents/workflows/<runId>/` directory exists from a prior run whose newest transcript `mtime` is older than the workflow liveness window and it is terminal
- **THEN** the run is not displayed

### Requirement: Grouped run rendering

The statusline SHALL render each visible workflow run as a distinct grouped block, placed after the normal subagent cohort and the task row. The block SHALL consist of a header row, zero or more per-agent rows, and a summary footer row. The header SHALL show a group glyph, the run name, and the current phase when known. Per-agent rows SHALL reuse the existing subagent row renderer so a workflow agent is visually identical to an ordinary subagent row at the same width. The summary footer SHALL show the agent count, the Done count, and the run's aggregate token total summed from the per-agent transcript parse.

#### Scenario: Wide block shows header, agents, and summary

- **WHEN** a run is visible at medium or wider width
- **THEN** the block renders a header (`▸ <name>  [<phase>]`), one row per agent (capped, see below), and a summary footer (`└ N agents · M done · <tok>`)

#### Scenario: Per-agent rows match the subagent row format

- **WHEN** a workflow agent row is rendered at a given width
- **THEN** it uses the same row renderer and field set as an ordinary subagent row (two-line above width 100, one-line otherwise)

#### Scenario: Aggregate tokens summed locally

- **WHEN** a run's summary footer renders its token total
- **THEN** the total is the sum of the per-agent transcript token parse, not the run JSON's reported total

### Requirement: Narrow-width collapse

At narrow width (below the medium threshold), the statusline SHALL collapse a workflow run to its header and summary only, omitting all per-agent rows, to protect vertical space.

#### Scenario: Narrow run shows header and summary only

- **WHEN** a run is visible and the layout width is below the medium threshold
- **THEN** only the header and summary rows render and no per-agent rows are shown

### Requirement: Per-run agent cap

The statusline SHALL render at most 6 per-agent rows for a single run. When a run has more than 6 agents, only the first 6 (ordered by `first_timestamp`) SHALL render and the remaining count SHALL be reflected in the summary footer.

#### Scenario: Overflowing run caps at six rows

- **WHEN** a run has 9 agents at a width that shows per-agent rows
- **THEN** 6 agent rows render and the summary notes the 3 hidden (e.g. `└ 9 agents · 4 done · +3 hidden`)

### Requirement: Concurrent run cap

The statusline SHALL render at most 2 workflow run blocks concurrently. When more than 2 runs are visible, the 2 most-recently-active runs (by newest agent `mtime`) SHALL render and the remaining count SHALL be noted on a single overflow line.

#### Scenario: Third concurrent run is summarised

- **WHEN** 3 runs are simultaneously visible
- **THEN** the 2 most-recently-active runs render as blocks and a one-line `+1 more workflows` note is shown
