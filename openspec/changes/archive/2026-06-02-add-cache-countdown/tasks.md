<!--
═══════════════════════════════════════════════════════════════════════════
  PROGRESS-MARKING PROTOCOL — READ BEFORE STARTING ANY TASK
═══════════════════════════════════════════════════════════════════════════

  This change is built to FAN OUT across multiple workers. Every agent —
  the main/orchestrating agent AND every subagent — MUST mark each subtask
  as done the INSTANT it is finished:

    • Flip `- [ ]` to `- [x]` in THIS file the moment a subtask is complete,
      BEFORE moving on to the next subtask. Do not batch updates. Do not wait
      until the end of a group. Do not rely on another agent to record it.
    • One edit per completed subtask, immediately. The checkbox state in this
      file is the single source of truth for live progress; stale checkboxes
      make the run look stalled and cause workers to duplicate or skip work.
    • If you pick up a subtask, you own recording its completion here.

  Accurate, real-time checkboxes are what let the orchestrator observe the
  spec's progress and dispatch the next worker correctly.

  FANOUT MAP (dependencies between groups):
    • Group 1 (constants)      — no deps; do FIRST. Unblocks 2, 4.
    • Group 2 (transcript)     — needs 1. Runs parallel with Group 4.
    • Group 3 (SessionView)    — needs 2.
    • Group 4 (renderer)       — needs 1. Runs parallel with Groups 2 & 3.
    • Group 5 (build_wide)     — needs 1–4 (integration; single owner).
    • Group 6 (tests)          — 6.1–6.3 parallel with their target group;
                                 6.4–6.5 need Group 5.
    • Group 7 (verify)         — last; needs everything.
═══════════════════════════════════════════════════════════════════════════
-->

## 1. Constants (foundational — do first, unblocks 2 & 4)

- [x] 1.1 Add `GLYPH_CACHE = ''  # nf-oct-cache` to the PUA glyph block in `claude/yas/constants.py`, encoded as a named escape per the PUA hoist rule
- [x] 1.2 Add `CACHE_TTL_SECONDS = 300` and `CACHE_TTL_1H_SECONDS = 3600` alongside the existing rate-limit window constants in `claude/yas/constants.py`

## 2. Transcript anchor extraction (needs Group 1; parallel with Group 4)

- [x] 2.1 Add raw fields `cache_anchor_epoch: float` (default `0.0`) and `cache_ttl: int` (default `0`) to `TranscriptUsage` in `claude/yas/info/transcript.py`
- [x] 2.2 In the existing single forward scan, retain the most-recent line whose usage has `cache_read_input_tokens > 0` or `cache_creation_input_tokens > 0` — keep its raw `timestamp` string and its 1h-tier flag (`cache_creation.ephemeral_1h_input_tokens > 0`); do NOT add a second pass
- [x] 2.3 After the loop, convert the retained timestamp string to epoch exactly once via the `session` ISO-to-epoch helper; on missing/malformed timestamp leave `cache_anchor_epoch = 0.0`. Set `cache_ttl` to `CACHE_TTL_1H_SECONDS` when the 1h flag is set, `CACHE_TTL_SECONDS` when there is an anchor without it, and `0` when there is no anchor

## 3. SessionView derivation (needs Group 2)

- [x] 3.1 Add a lazy `@cached_property cache_countdown` to `SessionView` in `claude/yas/info/__init__.py` reading `self.transcript_usage`'s raw anchor and the frozen `self.now`
- [x] 3.2 Compute `remaining = cache_ttl - (now - cache_anchor_epoch)` and `elapsed_pct = clamp(100 - round(remaining * 100 / cache_ttl), 0, 100)`; return `(remaining, elapsed_pct)` or `None` when there is no anchor (`cache_anchor_epoch == 0.0` or `cache_ttl == 0`) or `remaining <= 0`. Hold no ANSI/geometry

## 4. Renderer section helper (needs Group 1; parallel with Groups 2 & 3)

- [x] 4.1 Add a cache-section helper to `Renderer` in `claude/yas/renderer.py` that takes `(remaining, elapsed_pct)` and returns `(text, visible_width)`, rendering `GLYPH_CACHE` + a space + `fmt_dur(remaining)` with the value tinted by `self.fill_colour(elapsed_pct)`
- [x] 4.2 Compute the returned width with `_visible_width` (not `len`), counting `GLYPH_CACHE` as width 1

## 5. build_wide integration & elbow threading (needs Groups 1–4; single owner)

- [x] 5.1 In `build_wide` (`claude/yas/layout.py`), read `view.cache_countdown`; when present, build the cache section and insert it as a vsep-delimited block in the `pad` gap between `helper_text` and the model section, with a single left divider `│`
- [x] 5.2 Thread the new divider's 1-indexed column as an elbow into the path/model `top_border.downs` and the following `separator_dim.ups`, keeping the path divider elbow; verify `┬`/`│`/`┴` alignment
- [x] 5.3 Subtract the cache section's visible width (divider + glyph + value) from `target_w` and the `pad` computation so the model section/pill stays flush-right and `fit_path` truncates correctly
- [x] 5.4 Implement width-shed: when the row cannot fit path + helper + cache + model section, drop the cache section AND its divider FIRST (before truncating the path further) and re-thread elbows to only the path divider
- [x] 5.5 Ensure the hidden case (`cache_countdown is None`) also drops the divider and re-threads to only the path elbow — derive `downs`/`ups` from a single "section present" boolean so border math can never reference a missing `│`
- [x] 5.6 Confirm medium and narrow builders are untouched (no Cache Countdown there)

## 6. Tests

- [x] 6.1 (parallel w/ Group 2/3) `test_info.py`: countdown math — fresh (`90s`/`300s` → remaining 210, elapsed_pct 30), near-expiry colour band, expired → `None`, no-event → `None`, 1h tier, and frozen-`now` usage
- [x] 6.2 (parallel w/ Group 2) transcript test: `cache_anchor_epoch`/`cache_ttl` extraction — latest cache line wins, no-cache → `0.0`/`0`, 1h tier → `3600`, malformed timestamp → `0.0`
- [x] 6.3 (parallel w/ Group 2/3) `test_info.py`: assert the transcript is scanned exactly once when both `transcript_usage` and `cache_countdown` are read
- [x] 6.4 (needs Group 5) `test_layout_seam.py`: section renders with glyph + value + divider; divider column appears in top-border `downs` and separator `ups`; inject a `SessionView` with a known countdown
- [x] 6.5 (needs Group 5) `test_layout_seam.py`: divider drops and elbows re-thread to only the path divider when `cache_countdown is None`; width-shed drops the section first without extra path truncation; narrow/medium render no section

## 7. Verification (last; needs everything)

- [x] 7.1 Run `make test` — green, pass count = baseline + new tests
- [x] 7.2 Run the PUA catalogue check on touched files; confirm `GLYPH_CACHE` is referenced as the named constant, never a raw glyph
- [x] 7.3 Run `make demo` — eyeball the path/model row elbow alignment across wide widths, WITH and WITHOUT the thinking pill, and through the width-shed boundary
- [x] 7.4 Confirm `CONTEXT.md` Cache Countdown / Cache TTL glossary entry matches the shipped behaviour (labels, glyph, colour, hide rules)
