## Context

The wide layout (`build_wide` in `claude/yas/layout.py`) already reads the full
main transcript once per render via `view.transcript_usage`
(`TranscriptUsage.from_transcript`, `claude/yas/info/transcript.py`) and parses
every `agent-*.jsonl` subagent transcript via `view.subagents`
(`RunningSubagents.from_session` → `parse_transcript`,
`claude/yas/info/subagents.py`). Both already iterate the `message.content`
arrays and inspect `tool_use` blocks (subagents.py reads them for the activity
snippet). Counting `tool_use` blocks per tool name is therefore additive work on
bytes already in hand — no new file reads, no cache, no offset/incremental logic.

`SessionView` (`claude/yas/info/__init__.py`) is the lazy gather seam: every
derived field is a `@cached_property`, and `info` never imports `renderer`/
`layout`. It already exposes `transcript_usage`, `subagents`, and `clear_epoch`
(`read_clear_epoch`, `claude/yas/info/clear.py`, which returns the epoch of the
most-recent `/clear` marker or `None`).

The wide session-totals band is built in `build_wide` after the top/path row: a
labelled `separator_dim` (the "seam") then the `tokens_cost` content rows, then
conditional plugins / tasks / subagent / workflow / openspec rows. Conditional
rows follow a fixed pattern: append to a local `rows` list, thread `pending_ups`
through `sep_kind(...)`, and re-thread elbows when a row drops out. The new tool
row slots in immediately after the `tokens_cost` rows and before the plugins row.

Section labels are superscript captions overlaid on a separator's fill columns by
`_overlay_labels` (`claude/yas/render/borders.py`), which calls `superscript()`
(`claude/yas/render/text.py`). `superscript('tools main/sub')` yields exactly
`ᵗᵒᵒˡˢ ᵐᵃⁱⁿᐟˢᵘᵇ` (the `/`→`ᐟ` mapping is in `_SUPERSCRIPT`). Labels are gated on
`cfg.labels`, consistent with every other section's caption.

## Goals / Non-Goals

**Goals:**
- Show per-tool `main/sub` `tool_use` counts as a standalone full-width wide-only
  row under the tokens/cost row, greedy-filled to the available width.
- Correctly count the **final** streamed write per `message.id` (last-wins), since
  partial writes can contain fewer `tool_use` blocks than the final write.
- Window counts to "since last `/clear`"; whole-session when `clear_epoch` is None.
- Reuse the existing scans (`transcript_usage`'s file, the subagent cohort) — no
  new I/O, no cache.

**Non-Goals:**
- No timing/duration stats (min/max/avg/current) — counts only. Explicitly dropped.
- No per-subagent breakdown — `sub` is a single summed column across all subagents.
- No narrow/medium row — wide tier only.
- No config knob to toggle the row beyond the existing `cfg.labels` (which only
  controls the caption, as for every other section). The row itself is always
  present in wide when counts are non-zero.

## Decisions

### 1. New aggregator module `claude/yas/info/toolcounts.py`

A new module mirroring the shape of `transcript.py`/`subagents.py`: a small
`ToolCounts` dataclass plus parsing classmethods. `info` stays below `renderer`/
`layout` in the DAG.

```python
class ToolCounts:
    # tool name (MCP-normalized) -> (main_count, sub_count)
    counts: dict[str, tuple[int, int]]
    # convenience: number of distinct tool types (for +k overflow math)
```

API:
- `count_transcript(path: str, clear_epoch: float | None) -> dict[str, int]` —
  parse one transcript file, return `{tool_name: count}` for `tool_use` blocks at
  or after `clear_epoch`, deduped by `message.id` keeping the **last** occurrence,
  meta-excluded, MCP-normalized. Used for both the main file and each subagent
  file. Never raises (mirrors the `except OSError` / `try/except json` guards in
  the sibling parsers).
- `ToolCounts.gather(main_path, subagents, clear_epoch) -> ToolCounts` — call
  `count_transcript` on the main transcript (→ main column) and on each
  `RunningSubagent`'s transcript (→ summed into the sub column), merging into the
  `counts` dict. Subagents whose entire activity predates `clear_epoch` contribute
  nothing naturally (their tool_use messages are all filtered out by timestamp).

Reuse the ISO→epoch helper pattern: import `_parse_iso_to_epoch` from
`yas.info.subagents` (it already exists module-level there) rather than
re-implementing it, so the timestamp parse semantics match the rest of `info`.

`RunningSubagent` does not currently store its transcript path — it stores
`agent_id` (the filename stem) and parsed fields, not the `Path`. **Decision:** add
a `jsonl_path: str = ''` field to `RunningSubagent.__slots__`/`__init__` and set it
in `RunningSubagents.from_session` (the `jsonl` Path is already in scope there at
construction). This is the minimal seam to let `ToolCounts.gather` re-open each
subagent transcript. (Alternative — re-derive the path from `agent_id` + project
slug inside `toolcounts.py` — was rejected: it duplicates the slug logic and the
`from_session` directory walk.)

### 2. Dedup keeps the LAST occurrence per `message.id` (differs from siblings)

`tool_use` blocks carry no stable id of their own. Streaming writes the same
`message.id` several times: early partials (`stop_reason: null`) may contain
**fewer** `tool_use` blocks than the final write. To count the true number of tool
calls, we must count the content of the **last** write per `message.id`.

This is the opposite of `transcript.py` and `subagents.py`, which keep the
**first** occurrence per id (`if not mid or mid in seen: continue`). That is
correct for *token* accounting (usage is stable across the streamed writes and
first-wins avoids double-counting) but wrong for *tool-block counting* (first-wins
would undercount when the final write added blocks). Implementation: accumulate
`per_id: dict[str, list[str]]` mapping `message.id → list of tool names from the
most recent line seen for that id` (overwrite on each line for that id), then sum
the lists across ids after the scan. Lines with no `message.id` are skipped (same
as siblings). **This first-vs-last divergence is called out here explicitly so a
future reader does not "fix" it to match the sibling parsers.**

### 3. Window = since last `/clear` via per-message timestamp

Each transcript line carries a top-level `timestamp` (ISO-8601). Count a
`tool_use`-bearing line only when its `_parse_iso_to_epoch(timestamp) >=
clear_epoch`. When `clear_epoch is None`, count the whole transcript (no filter).
A subagent whose every line predates `clear_epoch` contributes zero — no separate
"drop the subagent" step is needed; the per-line timestamp filter subsumes it.

### 4. Eligibility: exclude a small meta set, KEEP `Task`

`META_EXCLUDE_TOOLS = frozenset({'TodoWrite', 'ExitPlanMode', 'AskUserQuestion'})`
in `constants.py`. These are todo/UI-plumbing tools, not "work". `Task` is **kept**:
it is the subagent-spawn tool (already mapped to `subagent_type` in
`renderer.TOOL_ARG_KEY`) and represents a delegation — a meaningful main-column
entry. The `Task` double-count is **intended**: a `Task` spawn counts once in the
main column, and that subagent's own Read/Bash/etc. count in the sub column. They
are different columns and additive, telling the delegations-vs-delegated-work
story. (StructuredOutput is a workflow-internal completion marker; it is not in the
exclude set but will simply appear as another tool if present — no special-casing.)

### 5. MCP name normalization to last segment

MCP tool names arrive as `mcp__server__tool`. Normalize to the last `__`-split
segment (`name.split('__')[-1]`) before counting/keying so the row stays readable.
Non-MCP names pass through unchanged. Done inside `count_transcript` so the
`ToolCounts.counts` keys are already display-ready.

### 6. Renderer helper `Renderer.tool_counts_row(counts, width, *, fill=1.0)`

A new section helper in `renderer.py`. Full-width content (no internal `│`
divider), so it returns just a single `str` line — **no `div_offset`**, no
`ups`/`downs` threading for the row itself.

- **Selection / ordering:** sort `counts.items()` by combined `(main + sub)`
  descending, ties broken alphabetically by name (stable frame-to-frame).
- **Greedy fill:** emit `Name m/s` entries separated by a fixed gap until the next
  entry would exceed the content width (`width - 4`), measured with
  `_visible_width` (never `len()`). Track how many tool **types** were emitted vs
  total; the remainder is `k`.
- **Overflow marker:** when `k > 0`, append `+k` (k = count of additional tool
  *types* not shown, NOT the sum of their calls). If `+k` itself would overflow,
  drop the last fitted entry to make room (so the marker is never clipped).
- **Visual:** `main` painted bright (a bright theme colour, e.g. `self.TOK` or
  `BOLD`+colour), the `/` painted dim (`self.LABEL`/`self.TOK_DIM`), `sub` painted
  SGR-faint via a new `FAINT = '\033[2m'` constant, reusing the active-bright /
  quiet-dim idiom already used elsewhere (mon's `apply_dim`, the `LABEL`/`TOK_DIM`
  pairs). Always render both sides of the slash (`5/0`, never bare `5`).

### 7. Placement, label, and zero-state in `build_wide`

Insert immediately after the `tokens_cost` content rows (the `for lt in
line_tokens` loop) and before the `plugins_line` block. Pattern:

```python
tc = view.tool_counts
if tc.counts:
    tool_line = r.tool_counts_row(tc.counts, width, fill=fill)
    tc_labels = [(TOOL_COUNTS_LABEL, 3)] if view.cfg.labels else []
    rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups, labels=tc_labels))
    rows.append(RowSpec('content', content=tool_line))
    pending_ups = ()
```

The leading separator uses `sep_kind(...)` so it correctly becomes the
`separator_seam` if it is the first post-tokens separator (closing the tokens
vseps), and threads `pending_ups` exactly like the plugins/tasks/subagent blocks
do. The label is the superscript-rendered `tools main/sub` (the overlay applies
`superscript()`); store the plain caption string as `TOOL_COUNTS_LABEL = 'tools
main/sub'` in `constants.py` so no raw superscript glyphs live in `layout.py`.

**Zero-state:** when `tc.counts` is empty (zero counted tool uses since `/clear`),
neither the separator nor the content row is appended — the row disappears, exactly
like `plugins_line` / `task_row` / `openspec_bars` already do. `pending_ups` is
left untouched so the next section (or the bottom border) inherits the tokens
vseps' `┴` elbows.

## Risks / Trade-offs

- [Double scan of subagent transcripts] `subagents.py` already parses each
  `agent-*.jsonl` for tokens/activity; `ToolCounts.gather` re-opens and re-reads
  them for tool counts. → Accepted: the design explicitly chose "rescan every
  render, no cache" for simplicity and correctness; subagent transcripts are small
  and the cohort is capped. A future optimization could have `parse_transcript`
  emit tool counts alongside its existing tuple, but that widens an already-wide
  return type and is out of scope.
- [Last-wins memory] Holding `per_id: dict[str, list[str]]` keeps a small list per
  message id for the duration of one file scan. → Bounded by message count of a
  single transcript; freed after each file. Negligible.
- [Row competes for vertical space] Adds one separator + one content row to the
  wide box when any tool ran. → Acceptable; it is conditional and only at wide
  width, alongside the other conditional band rows.

## Open Questions

- **Main bright colour choice.** Design specifies "bright" for `main` but leaves
  the exact theme token to the implementer (`self.TOK` vs `BOLD`+`self.CTX`). The
  visual test pins whatever is chosen; no semantic dependency. (Assumption made:
  reuse `self.TOK` bright / `FAINT` for sub / `self.LABEL` dim for the slash.)
- **Inter-entry gap width.** Example uses ~3 spaces between entries; the
  implementer may pick 2–3. The greedy-fill and `+k` math are independent of the
  exact gap. (Assumption: 3 spaces, matching the example row.)
