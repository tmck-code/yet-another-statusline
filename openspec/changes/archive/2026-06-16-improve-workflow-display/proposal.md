## Why

Workflow runs in YAS currently display agent prompts verbatim, which means multi-line tool commands bleed across rows and phase progress (a first-class concept in the claude workflow UI) is invisible. With workflows becoming a common usage pattern, the statusline needs to surface phase structure, handle multi-line content cleanly, and use screen real estate efficiently when wide terminals are available.

## What Changes

- Tool arguments in agent activity rows are truncated to the first line (no multi-line bleed)
- Workflow headers show the full ordered phase list inline (`Discover · ❯Scan · Verify · Synthesize`) with the current phase highlighted
- Done workflow agents render greyed with a frozen timer (verified to reach the existing `is_done` dim path)
- At terminal widths ≥ 160, workflow agents are paired side-by-side in two columns per row, halving vertical space usage

## Capabilities

### New Capabilities
- `workflow-phase-display`: Inline phase list in workflow run headers, parsed live from the workflow script's `meta.phases` and enriched with current-phase highlighting from the completion JSON
- `workflow-two-column-agents`: Two-column agent layout for workflow runs at wide terminal widths (≥ 160)

### Modified Capabilities
- `subagent-row-layout`: Tool-argument display now strips newlines to show only the first line

## Impact

- `claude/yas/info/workflows.py`: new `_parse_script_phases` function; `phases: list[str]` field on `RunningWorkflow`; `_enrich` debug logging removed
- `claude/yas/renderer.py`: `workflow_header` updated to render phase list; `subagent_activity` strips newlines from tool args
- `claude/yas/layout.py`: `build_workflow_rows` gains two-column pairing logic at width ≥ 160
- Tests: new cases for phase parsing, newline stripping, and two-column layout
