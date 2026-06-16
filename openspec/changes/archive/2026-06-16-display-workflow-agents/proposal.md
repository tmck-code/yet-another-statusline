## Why

The Workflow tool runs multi-agent orchestrations whose subagents are invisible to the statusline. yas globs `subagents/*.meta.json`, but workflow agents live a directory level deeper (`subagents/workflows/<runId>/`) and their `meta.json` carries only `{"agentType":"workflow-subagent"}` — no `description`, no per-agent type. So a user running a workflow sees nothing, even though several agents are actively burning tokens. We want to surface those agents, grouped by their workflow run, so the statusline reflects what is actually executing.

## What Changes

- Detect live workflow runs by globbing `subagents/workflows/<runId>/` directories under the session (a directory exists the instant an agent starts).
- Read the session-level `workflows/<runId>.json` opportunistically to enrich a run with its `workflowName`, current phase, and the `workflowProgress` `agentId → label` map. When the JSON is absent or stale, fall back to the transcript's first prompt line for the label and the `runId` for the header — detection never depends on JSON liveness.
- Reuse the existing transcript parser (`_parse_transcript`) for every workflow agent's tokens, activity snippet, and Done detection (`end_ts > 0`) — no new per-agent reader.
- Give workflow runs their own liveness window (~120s), separate from the subagent cohort's 30/60s windows, so a run survives between-phase lulls without flickering.
- Render each live run as a **distinct grouped block** after the normal subagent cohort and task row: a header (`▸ <name>  [<phase>]`), per-agent rows reusing `subagent_row`, and a summary footer (`└ N agents · M done · <tok>`). Narrow widths (<80) collapse a run to header+summary only. Per-run agent rows cap at 6 with overflow rolled into the summary. At most 2 workflow blocks render concurrently.

## Capabilities

### New Capabilities
- `workflow-cohort`: Detection, run-scoped grouping, liveness/retirement, and grouped rendering of agents spawned by the Workflow tool, including the run-JSON enrichment spine and its filesystem fallback.

### Modified Capabilities
<!-- None. The per-agent row rendering (subagent-row-layout) and Done detection
     (subagent-cohort) are reused verbatim; no existing requirement changes. -->

## Impact

- New reader module under `claude/yas/info/` (e.g. `workflows.py`) exposing a `RunningWorkflows.from_session(...)` analogous to `RunningSubagents`.
- New `@cached_property` on `SessionView` (`info/__init__.py`) constructing it.
- New `Renderer` helpers for the workflow header/footer rows; per-agent rows reuse `subagent_row`.
- New `RowSpec` wiring in `layout.py` `build_*` builders (narrow collapse, wide full, placement after the subagent cohort).
- New constants (the `▸`/`└` group glyphs, the liveness/cap thresholds) in `constants.py`.
- New tests: detection + label fallback, liveness/retirement, narrow collapse, agent cap, multi-run cap.
- `CONTEXT.md` glossary gains the workflow-run terms if any displayed label is canonical.
