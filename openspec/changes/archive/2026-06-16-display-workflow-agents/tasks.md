## 1. Constants and glyphs

- [x] 1.1 Add `GLYPH_WF_HEADER` (`▸`) and `GLYPH_WF_SUMMARY` (`└`) to `constants.py` as escape-encoded literals, alongside `ICON_COST`/`GLYPH_MODEL`
- [x] 1.2 Add `WORKFLOW_LIVENESS_SECONDS = 120`, `WORKFLOW_AGENT_CAP = 6`, and `WORKFLOW_RUN_CAP = 2` to `constants.py`

## 2. Reader: detection and parsing

- [x] 2.1 Lift `RunningSubagents._parse_transcript` to a shared module-level helper (or import it) so the workflow reader can call it without duplication
- [x] 2.2 Create `claude/yas/info/workflows.py` with a `RunningWorkflow` dataclass (`run_id`, `name`, `phase`, `agents: list[RunningSubagent]`) and derived `done_count`/`agent_count`/`total_tokens` properties
- [x] 2.3 Implement `RunningWorkflows.from_session(session_id, project_dir)`: glob `subagents/workflows/<runId>/agent-*.jsonl`, parse each via the shared transcript helper, group by `<runId>`, reusing the project-slug logic from `RunningSubagents.from_session`
- [x] 2.4 Implement run-JSON enrichment: parse `workflows/<runId>.json` when present; set `name` from `workflowName`, map `workflowProgress` `agentId → label` onto each agent, derive current phase from the latest `workflow_phase` progress index; never raise on missing/malformed JSON
- [x] 2.5 Implement fallback identity: name → `runId`; per-agent label → sanitized first non-empty line of the first user message in the transcript, middle-ellipsised; phase → omitted. Route all displayed strings through `_sanitize`

## 3. Liveness and visibility

- [x] 3.1 Implement `RunningWorkflows.visible(now, last_prompt_ts)`: keep a run while any agent `mtime` is within `WORKFLOW_LIVENESS_SECONDS` OR JSON status is non-terminal
- [x] 3.2 Implement retirement: drop a run once terminal (JSON terminal status OR all agents `end_ts > 0`) AND newest agent `mtime` is older than the grace window
- [x] 3.3 Order visible runs by newest agent `mtime` and cap concurrent runs at `WORKFLOW_RUN_CAP`, exposing the hidden-run count

## 4. SessionView seam

- [x] 4.1 Add a `workflows` `@cached_property` to `SessionView` (`info/__init__.py`) constructing `RunningWorkflows.from_session(...)` from the session id and project dir

## 5. Rendering

- [x] 5.1 Add `Renderer.workflow_header(run, width)` → `▸ <name>  [<phase>]` (phase omitted when unknown), width-clamped via `_visible_width`
- [x] 5.2 Add `Renderer.workflow_summary(run, width, *, hidden_agents)` → `└ N agents · M done · <tok>` with `+K hidden` when agents are capped
- [x] 5.3 Reuse `Renderer.subagent_row` for per-agent rows (`twoline=width>100`); cap at `WORKFLOW_AGENT_CAP` ordered by `first_timestamp`

## 6. Layout wiring

- [x] 6.1 In the wide/medium `build_*` builders, after the subagent cohort and task row, append a workflow block per visible run: header row, capped agent rows, summary row (as `RowSpec(kind='content')`)
- [x] 6.2 In the narrow `build_*` builder, collapse each run to header + summary rows only (no per-agent rows)
- [x] 6.3 When `WORKFLOW_RUN_CAP` is exceeded, append a single `+N more workflows` content row
- [x] 6.4 Re-thread surrounding border `ups`/`downs` for the added rows so elbows stay aligned

## 7. Tests

- [x] 7.1 `test_workflow_cohort.py`: detection from FS with no JSON; agentId from filename; ordinary subagents unaffected
- [x] 7.2 Enrichment: name + labels + phase from a fixture run JSON; malformed/missing JSON degrades to fallback identity
- [x] 7.3 Liveness: run survives a between-phase lull; settled run retires after grace; stale leftover dir not shown
- [x] 7.4 Rendering/layout: wide block (header/agents/summary), narrow collapse, 6-agent cap with `+K hidden`, 2-run cap with `+N more workflows`
- [x] 7.5 Done count uses `end_ts`; aggregate tokens summed from per-agent parse (not JSON `totalTokens`)

## 8. Verification and docs

- [x] 8.1 `make test` green (baseline + new tests); `ruff check` and `mypy .` clean
- [x] 8.2 `make demo` — eyeball a synthesised workflow block at narrow/medium/wide; verify `┬`/`│`/`┴` elbow alignment around the new rows
- [x] 8.3 Update `CONTEXT.md` glossary if any displayed workflow term (run name, phase, agent label) is canonical
