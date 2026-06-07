## Why

A subagent's activity-continuation line very often shows a bare `(replying)`
with no information. This happens because the activity verb is taken from the
*last* content block of the latest assistant message; assistant messages
frequently end with a `text` block (a narration or final summary), which the
renderer collapses to the literal `(replying)`. The line consumes space while
telling the user nothing about what the agent is doing.

## What Changes

- Change how the activity verb is derived from a subagent transcript message:
  prefer the **last `tool_use` block** in the message; only when no `tool_use`
  is present fall back to the **first non-empty line of the last `text` block**.
- Carry that text snippet (sanitized) through `last_activity` instead of
  discarding it, so a genuinely-narrating agent shows what it is saying rather
  than a contentless `(replying)`.
- Render the text case as the replying glyph followed by the snippet, reusing
  the existing 36-visible-column ellipsis cap already applied to tool args.
- `thinking` blocks are unchanged (`(thinking)`).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `subagent-row-layout`: the activity continuation's verb derivation is
  refined — last-`tool_use`-wins, with a text-snippet fallback replacing the
  bare `(replying)` placeholder.

## Impact

- `claude/yas/info/subagents.py` — `RunningSubagents._parse_transcript`
  (activity selection from message content; `last_activity` tuple now carries a
  text snippet).
- `claude/yas/renderer.py` — `Renderer.subagent_activity` (render the text
  snippet after `GLYPH_REPLYING`).
- Tests: `test/test_subagent_rows.py`, `test/test_subagent_metrics.py`.
- No change to stdin payload, layout geometry, or border math.
