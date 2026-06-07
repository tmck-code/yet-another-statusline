## Why

The context window is shown as a single fill bar with no breakdown of what is
consuming it (system prompt vs tool definitions vs plugins vs skills vs memory
vs messages). A by-source breakdown — like Claude Code's `/context` view — would
help users see where their context budget goes.

This proposal is **research / deferred**: investigation shows the data required
for a literal system-vs-plugins-vs-skills breakdown is **not available** to the
statusline today. It documents the gap, what *is* derivable, and what would be
required to do it properly, so the work is not silently re-attempted.

## What Changes

- **No implementation.** This change records findings and a decision to defer.
- Documents that the stdin payload's `context_window` exposes only totals and a
  single `current_usage` (`input` / `output` / `cache_creation` / `cache_read`)
  — no per-source split.
- Documents that the transcript's `attributionSkill` / `attributionPlugin`
  fields attribute a *message's token usage to the active skill/plugin*, not the
  *system prompt's composition*; they cannot reconstruct a `/context`-style
  breakdown.
- Records the two *feasible* alternatives discovered, for a future change to
  pick up if desired:
  - per-skill / per-plugin cumulative token attribution (sum transcript usage
    grouped by `attributionSkill`/`attributionPlugin`);
  - a structural split of current usage into cached base (`cache_read`) vs fresh
    input vs output.

## Capabilities

### New Capabilities
- `context-source-breakdown`: a documented constraint and deferral — the
  statusline SHALL NOT present a system/plugins/skills context breakdown it
  cannot derive; the feasible alternatives are recorded for future work.

### Modified Capabilities
<!-- none -->

## Impact

- No code change in this proposal.
- Reference points for any future implementation: `claude/yas/session.py`
  (`ContextWindow`, `CurrentUsage`), `claude/yas/info/transcript.py`
  (`TranscriptUsage`), and the `attributionSkill`/`attributionPlugin` transcript
  fields.
