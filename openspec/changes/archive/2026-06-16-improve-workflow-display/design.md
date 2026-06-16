## Context

YAS discovers workflow runs from the filesystem (`subagents/workflows/<runId>/`) and enriches them from a completion-only run JSON (`workflows/<runId>.json`). During a live run the run JSON does not exist; only the agent transcript files and a `journal.jsonl` (containing `started`/`result` entries with agent IDs, no phase data) are present. The workflow script is always written to `workflows/scripts/<name>-<runId>.js` at run start and contains the full `meta.phases` array.

Agent labels (`scan:injection` etc.) and the current phase string come from the run JSON's `workflowProgress` entries and are only available post-completion. During a live run, agent labels fall back to the first line of each agent's prompt.

## Goals / Non-Goals

**Goals:**
- Strip newlines from tool-argument display in all agent rows (workflow and ordinary subagents)
- Show all phase titles inline in the workflow header, from the script file (live) and with current-phase highlight from the run JSON (post-completion)
- Verify done-agent greying reaches workflow agents (existing code path, no new logic)
- Pair workflow agents side-by-side at width ≥ 160 to halve vertical space usage

**Non-Goals:**
- Per-phase agent grouping or phase-scoped agent counts (requires phase→agent mapping not available live)
- Knowing the current phase during a live run (not in any on-disk structure)
- Changing the liveness/retirement logic for workflows

## Decisions

### Phase data source: script file, not journal
The `journal.jsonl` carries only `started`/`result` entries — no phase data. The run JSON only exists at completion. The workflow script (`workflows/scripts/*-<runId>.js`) is available from run start and contains `meta.phases` with all phase titles. Decision: parse phases from the script file with a narrow regex (`phases:\s*[` ... `]`).

*Alternative considered*: parse `phase()` call sites from the script body to infer which phase an agent belongs to. Rejected — brittle, requires JS parsing, and per-phase counts aren't in scope.

### Phase list rendering: inline in header row
Putting the phase list in the existing header row (`▸  name  P1 · ❯P2 · P3`) keeps the row count fixed and avoids new RowSpec kinds. The name middle-ellipsises when the phase list is wide; the phase list truncates with `…` only when the name is already at minimum width.

*Alternative considered*: dedicated phase row below the header. Rejected — adds a row per workflow even when phase info is sparse; the inline form is more compact.

### Two-column threshold: 160 columns
Below 160, one-line agent rows already compress well. At 160+, pairing halves the row count without making either half too narrow (each half gets `(width - 4 - 5) // 2 ≈ 75` columns at the threshold). Pairs are formed sequentially by `first_timestamp` order; done+running can be mixed in a pair.

### Newline stripping: at display time, not parse time
`subagent_activity` is the only consumer that renders tool args into a single terminal line. Stripping at parse time (`parse_transcript`) would silently discard data that callers might want (e.g. future multi-line rendering). Strip in `subagent_activity` only, immediately after `raw` is assigned.

## Risks / Trade-offs

- **Script regex fragility**: If a workflow script uses backtick strings or unusual formatting for `title:`, the regex may miss phases. Mitigation: the fallback is an empty list, which degrades gracefully to the existing `[phase]` bracket style.
- **Two-column width math**: The right column must be padded to exactly `half_w` columns (using `_visible_width`) to avoid border misalignment. ANSI codes must not be counted in the width. Mitigation: use `_visible_width` for all column math, pad with spaces to `half_w` before joining.
- **Phase list overflow**: A workflow with many long phase names can overflow the header. Mitigation: truncate the phase list string with `…` when it would crowd the name below a minimum (e.g. 8 chars).

## Migration Plan

No on-disk format changes. The `phases` field on `RunningWorkflow` is a new in-memory field populated on each render; existing completed-run JSON files continue to work unchanged. No rollback needed — reverting any file restores prior behaviour.
