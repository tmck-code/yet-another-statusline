## 1. Constants

- [x] 1.1 In `claude/yas/constants.py` add `META_EXCLUDE_TOOLS = frozenset({'TodoWrite', 'ExitPlanMode', 'AskUserQuestion'})`.
- [x] 1.2 In `claude/yas/constants.py` add `FAINT = '\033[2m'` (SGR faint/dim) alongside the existing `BOLD`/`ITALIC` codes.
- [x] 1.3 In `claude/yas/constants.py` add `TOOL_COUNTS_LABEL = 'tools main/sub'` (plain ASCII; the separator overlay applies `superscript()` so no raw superscript glyphs live in source).

## 2. Subagent transcript path seam

- [x] 2.1 In `claude/yas/info/subagents.py` add a `jsonl_path: str = ''` field to `RunningSubagent.__slots__`, its `__init__` signature, the assignment, `_key()`, and `__repr__` (keep the existing field order/style).
- [x] 2.2 In `RunningSubagents.from_session`, pass `jsonl_path=str(jsonl)` when constructing each `RunningSubagent` (the `jsonl` Path is already in scope).
- [x] 2.3 Update existing subagent tests/fixtures that compare `RunningSubagent` equality or repr to account for the new field (search `test/test_subagent_rows.py`, `test/test_cohort_visibility.py`, `test/test_subagent_metrics.py`).

## 3. Aggregator module

- [x] 3.1 Create `claude/yas/info/toolcounts.py` with a `ToolCounts` class (slots or dataclass, matching the `info` module style) holding `counts: dict[str, tuple[int, int]]` (tool name → `(main, sub)`) and a `type_count` / `total_types` accessor for `+k` math.
- [x] 3.2 Implement `count_transcript(path: str, clear_epoch: float | None) -> dict[str, int]`: open the file with `errors='ignore'`; for each line, fast-reject non-`tool_use` lines (`'"tool_use"' not in ln`) before `json.loads`; parse `message.id` and the top-level `timestamp`; skip lines with no `message.id`; when `clear_epoch is not None`, skip lines whose `_parse_iso_to_epoch(timestamp) < clear_epoch`; build `per_id: dict[str, list[str]]` overwriting each id with the tool names of the **current** line (last-write-wins); after the scan, flatten `per_id` values into a `dict[str, int]` count. Apply `META_EXCLUDE_TOOLS` filtering and `name.split('__')[-1]` MCP normalization when collecting tool names. Guard all parsing with `try/except (ValueError, TypeError)` and the file open with `try/except OSError`, returning `{}` on failure (mirror `transcript.py`/`subagents.py`).
- [x] 3.3 Import `_parse_iso_to_epoch` from `yas.info.subagents` (reuse, do not reimplement).
- [x] 3.4 Implement `ToolCounts.gather(main_path: str, subagents: list[RunningSubagent], clear_epoch: float | None) -> ToolCounts`: call `count_transcript(main_path, clear_epoch)` into the main column; for each subagent call `count_transcript(sub.jsonl_path, clear_epoch)` and sum into the sub column; merge both into `counts` so every key has a `(main, sub)` tuple (zero-fill the missing side).
- [x] 3.5 Add a module docstring that explicitly states the last-write-wins dedup and why it differs from `transcript.py`/`subagents.py` (which keep first-wins — correct for tokens, wrong for tool-block counting).

## 4. SessionView seam

- [x] 4.1 In `claude/yas/info/__init__.py` import `ToolCounts` from `yas.info.toolcounts` and add a `tool_counts` `@cached_property` to `SessionView` that returns `ToolCounts.gather(self.session.transcript_path, self.subagents.subagents, self.clear_epoch)`. Place it near `transcript_usage`/`session_inout`, following the existing cached_property pattern. Do not import `renderer`/`layout`.

## 5. Renderer helper

- [x] 5.1 In `claude/yas/renderer.py` add `tool_counts_row(self, counts: dict[str, tuple[int, int]], width: int, *, fill: float = 1.0) -> str`.
- [x] 5.2 Sort `counts.items()` by `(-(main + sub), name)` so combined total descends with alphabetical tie-break.
- [x] 5.3 Greedy-fill `Name m/s` entries (gap of 3 spaces between entries) into the content width `width - 4`, measuring with `_visible_width` (import from `yas.render.text`); track shown vs total tool types.
- [x] 5.4 Colour each entry: name in a neutral colour, `main` bright (`self.TOK`), `/` dim (`self.LABEL`), `sub` faint (`FAINT` from `yas.constants`); reset with `self.R`. Always emit both sides of the slash.
- [x] 5.5 When unshown types remain, append `+k` (k = unshown TYPE count) styled like the existing `+N` overflow markers (`self.LABEL`); if appending `+k` would exceed the content width, drop the last fitted entry first so the marker is never clipped.
- [x] 5.6 Return a single `str` (no `div_offset`, no internal `│`).

## 6. Layout wiring

- [x] 6.1 In `claude/yas/layout.py` `build_wide`, import `TOOL_COUNTS_LABEL` from `yas.constants`.
- [x] 6.2 Immediately after the `tokens_cost` content rows (`for lt in line_tokens: rows.append(...)`) and before the `plugins_line` block, read `tc = view.tool_counts`; when `tc.counts` is non-empty, append `RowSpec(sep_kind('separator_dim'), ups=pending_ups, labels=[(TOOL_COUNTS_LABEL, 3)] if view.cfg.labels else [])` then `RowSpec('content', content=r.tool_counts_row(tc.counts, width, fill=fill))`, then set `pending_ups = ()`.
- [x] 6.3 When `tc.counts` is empty, append nothing and leave `pending_ups` untouched (zero-state; surrounding elbow threading inherits the tokens vseps' `┴`).
- [x] 6.4 Verify the `sep_kind`/`seam_pending` interaction: when the tool row is the first post-tokens section it correctly draws as `separator_seam`, and subsequent sections (plugins/tasks/...) then use normal `separator_dim` (no regression to the existing seam behaviour).

## 7. Tests

- [x] 7.1 Create `test/test_tool_counts.py` for the parser, importing `from yas.info.toolcounts import ToolCounts, count_transcript`. Cover: per-tool counting; `message.id` dedup keeping the LAST write (partial-then-fuller-final); repeated identical final write not double-counted; `clear_epoch` filtering (before excluded, None counts all); meta-exclude drops `TodoWrite`/`ExitPlanMode`/`AskUserQuestion` and KEEPS `Task`; MCP `mcp__server__tool` → last-segment normalization; main-vs-sub aggregation summed across multiple subagent transcripts. Use `tmp_path`-written JSONL fixtures with real `timestamp` fields.
- [x] 7.2 Add a render/layout test (e.g. in `test/test_layout_seam.py` or a new `test/test_tool_counts_row.py`) that injects a `SessionView` constructed from a known `SessionInfo` + `Config` (not raw reader data) and asserts: the row appears in `build_wide` and is absent in narrow/medium; greedy-fill respects width with `+k` showing the TYPE count (not call sum); bright/faint/dim treatment present (assert the `FAINT` code appears on the sub value); zero-state omits both the row and its separator. Width assertions go through `_visible_width`.
- [x] 7.3 Run `make test` via the verifier and confirm pass count = baseline + new tests, and `make demo/img` + the yas-demo-text diff shows the new row only at wide width with straight elbows.

## 8. Docs

- [x] 8.1 In `CONTEXT.md` add glossary entries for the new tool-counts row and the `main/sub` column meaning (main = main-session tool_use count since last `/clear`; sub = summed count across all subagents), keeping the displayed-terms glossary in sync per the post-edit checklist.
