## Context

The Workflow tool spawns multi-agent runs whose subagents are written to disk under the session, but one directory level below where yas looks. Today `RunningSubagents.from_session` globs `subagents/*.meta.json`; workflow agents sit at `subagents/workflows/<runId>/agent-*.{jsonl,meta.json}` and their `meta.json` is just `{"agentType":"workflow-subagent"}` — no `description`, no per-agent type. The richer per-run data (name, phases, an `agentId → label` map, status) lives in a session-level snapshot `workflows/<runId>.json`, and an append-only `journal.jsonl` sits beside the agents recording `started`/`result` events.

The existing subagent pipeline is reusable in two places: the transcript parser (`RunningSubagents._parse_transcript`) already extracts tokens, the activity snippet, `first_timestamp`, `mtime`, and `end_ts` from any `agent-*.jsonl`; and `Renderer.subagent_row` already renders a single agent at any width. What's missing is (a) a reader that discovers runs and groups their agents, (b) a run-scoped liveness model, and (c) grouped header/footer rendering.

Constraints: the renderer is a single-pass column-math painter (see `tmck-code-statusline` skill); new glyphs must be hoisted to `constants.py` as escapes; width math goes through `_visible_width`; new on-disk readers live under `info/` and surface via a `SessionView` `@cached_property`; layout decisions live in `build_*`, not `render_layout`.

## Goals / Non-Goals

**Goals:**
- Surface live workflow agents grouped by their run, with meaningful labels and the run name/phase when available.
- Make detection robust to the run JSON's unknown liveness behaviour — a run is detectable from the filesystem alone.
- Reuse `_parse_transcript` and `subagent_row` rather than duplicating parsing/rendering.
- Keep the normal subagent cohort behaviour untouched.

**Non-Goals:**
- No per-phase nesting of agent rows. Phase is a header hint only; agents render flat.
- No dependency on `journal.jsonl` for Done/running status — `end_ts` from the transcript is the single source, matching the subagent cohort.
- No trust in the run JSON's `totalTokens`/`status` as load-bearing; they are hints/enrichment.
- No change to ordinary subagent detection, rows, or windows.

## Decisions

### Decision: Filesystem is the detection spine; run JSON enriches

A run is detected by the `subagents/workflows/<runId>/` directory existing with at least one agent transcript. The directory and `agent-*.jsonl` files exist the moment an agent starts, so live detection cannot depend on when (or whether) `workflows/<runId>.json` is written.

*Why over JSON-as-spine:* **confirmed empirically** by running a live two-agent workflow — while both agents were active (transcripts growing, `journal.jsonl` present with `started`/`result` events), `workflows/<runId>.json` did **not exist**; only `workflows/scripts/` was present. The run JSON is written at **completion only**. A JSON-spine design would therefore show workflows *only after they finish* — the exact opposite of the goal. Filesystem detection is immune to that.

*Enrichment:* when `workflows/<runId>.json` parses, take `workflowName`, the `workflowProgress` `agentId → label` map, and the current phase. Match labels to agents by `agentId` (the transcript filename stem). **Because the JSON is completion-only, during a live run the per-field fallbacks are the _primary_ path, not an edge case:** name → `runId`, label → sanitized first prompt line, phase → omitted. The JSON enrichment effectively only upgrades the labels/name once the run has already finished (and is in its retirement grace window).

### Decision: New `info/workflows.py` reader, parallel to `info/subagents.py`

Add `RunningWorkflow` (one run: `run_id`, `name`, `phase`, `agents: list[RunningSubagent]`, plus derived counts) and `RunningWorkflows` with `from_session(session_id, project_dir)` and a `visible(now, last_prompt_ts)` method. Reuse `RunningSubagent` as the per-agent dataclass and call the existing `_parse_transcript` (lift it to a shared helper if needed) so token/activity/Done logic is identical to the cohort. The session/project slug logic is copied from `RunningSubagents.from_session`.

*Why a new module over extending `RunningSubagents`:* the grouping unit (a run) and the liveness window differ; folding both into one class would tangle two cohorts with different retirement rules. A sibling reader keeps each cohort's rules legible and testable in isolation (`test_workflow_cohort.py` parallel to `test_cohort_visibility.py`).

### Decision: Run-scoped liveness, ~120s, independent of subagent windows

A run stays visible while any agent `mtime` is within `WORKFLOW_LIVENESS_SECONDS` (default 120) OR the JSON status is non-terminal; it retires once terminal (JSON terminal status, or all agents `end_ts > 0`) AND newest `mtime` is older than a grace window (~20–30s, may reuse the cohort grace constant).

*Why not reuse the cohort's 30/60s windows:* workflows run for minutes and an agent can sit Done-and-idle between phases longer than 60s; the cohort windows would retire a live run mid-flight and then re-show it, causing flicker. The longer window rides through lulls.

### Decision: Reuse `subagent_row`; new helpers only for header/footer

Per-agent rows call the existing `Renderer.subagent_row(sub, width, twoline=width>100, ...)`. New `Renderer` helpers render only the group header (`▸ <name>  [<phase>]`) and summary footer (`└ N agents · M done · <tok>`). Group glyphs (`▸`, `└`) and thresholds are constants in `constants.py`. The block is assembled in the `build_*` builders as a sequence of `RowSpec(kind='content')` rows placed after the subagent cohort and task row.

*Why:* visual consistency with the normal cohort for free, and no new border `kind` — the block is plain content rows inside the existing box.

### Decision: Caps and collapse handled in `build_*`, summarised in the footer

Narrow (<`MEDIUM_WIDTH`) → header+summary only. Per-run agent rows cap at 6 (ordered by `first_timestamp`), overflow folded into the footer (`+K hidden`). Concurrent runs cap at 2 (most-recently-active by newest `mtime`), overflow on a single `+N more workflows` line. Any silent truncation is reflected in the footer/overflow text, never dropped invisibly.

## Risks / Trade-offs

- **[Run JSON is actually completion-only] →** Filesystem-spine design already covers this; labels degrade to prompt lines and the header to `runId`, but agents still appear live. Acceptable.
- **[Run JSON is written but lags / has stale `workflowProgress`] →** Labels may briefly be the fallback prompt line until the JSON catches up; never blocks detection. Acceptable.
- **[Leftover run directories from prior runs] →** The liveness window + terminal check retire them; a stale terminal dir older than the window never shows.
- **[Phase derivation is fragile]** — in the one observed JSON, agent `phase` fields were null and phase boundaries were separate `workflow_phase` progress events, so position-based phase assignment is unreliable. *Mitigation:* treat phase as a best-effort header hint derived from the latest `workflow_phase` progress index; omit it entirely rather than guess wrong.
- **[Vertical space blowout]** — many agents across multiple runs could dominate the box. *Mitigation:* the 6-agent and 2-run caps plus narrow collapse bound the height.
- **[Untrusted input]** — agent labels/snippets and the workflow name come from model/tool output. *Mitigation:* route every displayed string through the existing `_sanitize` used by the subagent path.

## Open Questions

- Exact terminal-status string(s) in `workflows/<runId>.json` (`completed` confirmed; are there `failed`/`cancelled`?). Treat any non-`running`/non-empty terminal-looking status as terminal, and rely on the `all end_ts > 0` filesystem check as the real retirement signal so this is not load-bearing.
- Whether `journal.jsonl` is worth reading at all. Current design does not need it; left as a future enrichment if `end_ts` proves insufficient for interrupted agents.
