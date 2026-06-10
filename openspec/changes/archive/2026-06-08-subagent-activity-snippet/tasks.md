## 1. Activity selection in the data layer

- [x] 1.1 In `RunningSubagents._parse_transcript` (`claude/yas/info/subagents.py`), replace the `content[-1]` check with: scan `content` for the last `tool_use` block and record it; if none, find the last `text` block and record its first non-empty line; else record `thinking`.
- [x] 1.2 Sanitize the extracted text line with `_sanitize` and store it as `('text', snippet, {})` in `last_activity` (keep `tool_use` and `thinking` tuples as they are).

## 2. Rendering

- [x] 2.1 In `Renderer.subagent_activity` (`claude/yas/renderer.py`), render the `text` case as `f'{GLYPH_REPLYING} {snippet}'`, applying the existing `_visible_width(raw) > 36` → `raw[:36] + '…'` cap.
- [x] 2.2 When the snippet is empty, fall back to the existing `(replying)` string so the line is never blank.

## 3. Tests

- [x] 3.1 Add a test (in `test/test_subagent_rows.py`) asserting a text-only latest message yields `GLYPH_REPLYING <snippet>` with the first non-empty line.
- [x] 3.2 Add a test asserting a message with both `tool_use` and trailing `text` renders the tool verb, not the snippet.
- [x] 3.3 Add a test asserting a snippet longer than 36 visible columns is truncated with `…`, and that an empty/absent text content falls back to `(replying)`.

## 4. Verification

- [x] 4.1 Run `make test` — green, baseline + new tests.
- [x] 4.2 Run `make demo` — eyeball a subagent row; confirm the activity line shows snippets and the box stays aligned.
