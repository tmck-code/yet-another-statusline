## Why

The prompt cache has a short TTL (5 minutes by default, 1 hour on the ephemeral-1h tier), and once it lapses the next turn pays full input price instead of the 0.1× cache-read rate. Nothing on the statusline tells the user how long they have before that happens, so a pause that silently crosses the expiry boundary is invisible until the cost shows up. A live **Cache Countdown** makes the remaining cache window observable at a glance.

## What Changes

- Add a **Cache Countdown** section to the **wide** layout's path/model row: `<cache-glyph> <m:ss>` (e.g. `3m07s`, `42s`) in its own vsep-delimited section between the rate-limit helper and the model pill, with a single left divider; the model pill stays flush-right.
- Derive the anchor from the transcript: the `timestamp` of the most recent line that touched the prompt cache (`cache_read_input_tokens > 0` or `cache_creation_input_tokens > 0`). `remaining = ttl − (now − anchor)`, re-derived every render against the frozen `now` — **no per-session state file**.
- Detect the TTL tier per anchor line: 300 s default, 3600 s when `cache_creation.ephemeral_1h_input_tokens > 0`.
- Colour the figure by `fill_colour(elapsed_pct)` (theme safe/warn/alert), where `elapsed_pct = 100 − round(remaining·100/ttl)` — green when fresh → red near expiry.
- Hide the whole section (divider included) when there has never been a cache event, when `remaining ≤ 0` (expired), or under width pressure — in which case it sheds **first**, before the path truncates.
- Extend the gather layer: `TranscriptUsage` carries the raw cache anchor; `SessionView` exposes a derived `cache_countdown`.
- Medium and narrow layouts are unchanged. Not a breaking change.

## Capabilities

### New Capabilities
- `cache-countdown`: deriving the prompt-cache expiry countdown (transcript anchor extraction, TTL-tier detection, remaining/elapsed-pct math) and rendering it as a width-shed-able, vsep-delimited section on the wide path/model row.

### Modified Capabilities
- `statusline-info`: `SessionView`'s enumerated derived-field set gains a lazily-evaluated `cache_countdown`, and `TranscriptUsage` gains raw cache-anchor fields populated in its existing single transcript scan.

## Impact

- **Code**: `claude/yas/constants.py` (glyph + TTL constants), `claude/yas/info/transcript.py` (`TranscriptUsage` anchor fields), `claude/yas/info/__init__.py` (`SessionView.cache_countdown`), `claude/yas/renderer.py` (cache-section helper), `claude/yas/layout.py` (`build_wide` section insertion, elbow threading, width-shed).
- **Docs**: `CONTEXT.md` glossary already carries the **Cache Countdown** / **Cache TTL** terms.
- **Tests**: `test/` additions for anchor extraction, countdown math, divider drop-and-rethread, and width-shed.
- **Dependencies / APIs**: none added; reads only existing transcript fields and the frozen-`now` clock.
