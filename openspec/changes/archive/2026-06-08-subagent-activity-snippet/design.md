## Context

`RunningSubagents._parse_transcript` (`claude/yas/info/subagents.py`) walks a
subagent's `.jsonl` transcript and, for the latest assistant message with a
usage block, records `last_activity` from `content[-1]`:

- `tool_use` → `('tool_use', name, input_dict)`
- `thinking` → `('thinking', '', {})`
- `text` → `('text', '', {})`  ← snippet is discarded

`Renderer.subagent_activity` (`claude/yas/renderer.py:588`) maps `text` to the
bare `f'{GLYPH_REPLYING} (replying)'`.

Within a single assistant message Claude usually emits `[text, tool_use]`, so
`content[-1]` is already the tool — `(replying)` predominantly appears when a
message *ends* in text (a narration or final summary), where there is genuine
text we are throwing away.

## Goals / Non-Goals

**Goals:**
- Replace bare `(replying)` with the agent's actual narration text when no tool
  call is present.
- Prefer a `tool_use` block over text within the same message, even when text
  is the trailing block.
- Keep the change confined to the data-selection (`_parse_transcript`) and
  render (`subagent_activity`) seams; no layout/geometry change.

**Non-Goals:**
- Scanning backwards across multiple messages for the "most meaningful" action.
- Multi-line snippets or rich formatting.
- Any change to token/duration/cluster fields or border math.

## Decisions

- **Selection in `_parse_transcript`:** iterate the message `content` and pick
  the last `tool_use` block if any exists; otherwise the last `text` block;
  otherwise `thinking`. This makes tool-use win regardless of position, fixing
  interleaved `[text, tool_use, text]` shapes too.
- **Snippet extraction:** take the first non-empty line of the chosen text
  block (`.splitlines()` → first stripped truthy line), run it through
  `_sanitize` (untrusted-input hardening), and store it in the `last_activity`
  tuple as `('text', snippet, {})` — reusing the existing `name` slot rather
  than widening the tuple.
- **Rendering:** `subagent_activity` renders the `text` case as
  `f'{GLYPH_REPLYING} {snippet}'`, applying the existing 36-visible-column cap
  (the same `_visible_width(raw) > 36` → `raw[:36] + '…'` logic already used for
  `tool_use` args). When the snippet is empty (no text content at all), fall
  back to the current `(replying)` string so the row is never blank.
- **Constants:** `GLYPH_REPLYING` already exists in `constants.py`; no new PUA
  glyph needed.

## Risks / Trade-offs

- **Untrusted text in the statusline:** subagent narration is model/file-derived
  text. Mitigated by routing it through `_sanitize` exactly as tool args are.
- **Snippet relevance:** the first line of a long narration may be a preamble
  rather than the salient action. Accepted — it is strictly more informative
  than `(replying)`, and the 36-col cap bounds it.
- **Truncation byte-safety:** slicing `raw[:36]` on a sanitized string matches
  the existing tool-arg behavior; `_visible_width` governs the threshold so
  ANSI/wide chars are accounted for consistently.
