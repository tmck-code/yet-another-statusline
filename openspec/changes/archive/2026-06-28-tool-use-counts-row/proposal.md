## Why

The wide statusline shows token/cost totals but no signal about *what kind of
work* drove them — how many times each tool ran, and how that work split between
the main session and its delegated subagents. A per-tool count row turns the
abstract token total into a legible "5 Bash, 8 Reads, 4 delegations" story, and
the main-vs-sub split makes the "delegations vs delegated work" pattern visible
at a glance. The counts are essentially free: the bytes are already read every
render by `transcript_usage` and the subagent cohort scan.

## What Changes

- Add a new wide-only statusline row in the session-totals band, directly **under**
  the tokens/cost row, showing per-tool `Name main/sub` counts (e.g.
  `Bash 5/12   Read 8/40   Edit 3/0   Task 4/0   +1`) where `main` = count in the
  main transcript and `sub` = summed count across **all** this session's subagents.
- Add a new gather aggregator `claude/yas/info/toolcounts.py` that counts
  `tool_use` blocks by tool name, split main vs sub, deduping by `message.id`
  keeping the **last** occurrence per id, filtered to messages at/after the last
  `/clear` (`SessionView.clear_epoch`), excluding a small meta set of tools, and
  normalizing MCP tool names to their last segment.
- Expose it as a new `tool_counts` `@cached_property` on `SessionView`
  (`claude/yas/info/__init__.py`).
- Render the row via a new `Renderer.tool_counts_row(...)` helper that greedy-fills
  to the wide width, sorts tools by combined `(main+sub)` total descending (alpha
  tie-break), colours `main` bright / `sub` SGR-faint / `/` dim, and emits an
  overflow marker `+k` where `k` = number of additional tool **types** not shown.
- Thread the row into `build_wide` as a conditional `RowSpec('content', ...)`
  preceded by a `separator_dim` carrying the superscript label `ᵗᵒᵒˡˢ ᵐᵃⁱⁿᐟˢᵘᵇ`.
  The row (and its separator) **disappear** entirely when there are zero counted
  tool uses since the last `/clear`.
- Add `META_EXCLUDE_TOOLS` (frozenset) and a `FAINT` SGR constant to
  `claude/yas/constants.py`.

Narrow and medium layouts are unaffected. No on-disk cache and no incremental
reading are introduced — the aggregator is a full rescan piggybacked on the scans
that already run each render.

## Capabilities

### New Capabilities
- `tool-counts-row`: per-tool main/sub `tool_use` counts as a wide-only session-
  totals row — the aggregation semantics (dedup, clear-window, meta-exclude, MCP
  normalization, main-vs-sub split), the top-N-by-combined selection with `+k`
  type overflow, the bright/faint/dim visual treatment, and the placement/label/
  zero-state rules in `build_wide`.

### Modified Capabilities
- `statusline-info`: add a render-independent `SessionView.tool_counts`
  `@cached_property` exposing per-tool `(main, sub)` counts and the total
  tool-type count, constructed from the main transcript, the subagent cohort, and
  `clear_epoch` (all already on the view).

## Impact

- `claude/yas/info/toolcounts.py` — new aggregator module + `ToolCounts` dataclass.
- `claude/yas/info/__init__.py` — new `tool_counts` `@cached_property` on `SessionView`.
- `claude/yas/renderer.py` — new `tool_counts_row(...)` section helper.
- `claude/yas/layout.py` — `build_wide` appends the conditional row + labelled
  separator under the tokens/cost row, re-threading `pending_ups`/`tail_ups`.
- `claude/yas/constants.py` — new `META_EXCLUDE_TOOLS` frozenset, `FAINT` SGR
  constant, and the `ᵗᵒᵒˡˢ ᵐᵃⁱⁿᐟˢᵘᵇ` label text constant.
- `test/test_tool_counts.py` (new, parser) and a render/layout test for the row.
- `CONTEXT.md` — glossary entries for the new row and the `main/sub` column meaning.
