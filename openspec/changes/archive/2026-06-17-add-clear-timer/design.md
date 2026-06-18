## Context

The wide top row renders a single session timer in `elapsed_section` (`renderer.py`), fed by `SessionView.elapsed` (= `_fmt_elapsed_clock(cost.total_duration_ms)`). The timer lives in one vsep-delimited cell in `build_wide` (`layout.py`) with a single divider/elbow (`elapsed_div_col`); the cell sheds entirely when the path would drop below 5 visible columns. Narrow/medium layouts never show the timer.

Empirically, `/clear` forks a **new** transcript file with a new `session_id` and writes a `<command-name>/clear</command-name>` user marker near the top (line 3 in every observed sample). The user confirmed `cost.total_duration_ms` keeps counting across the fork, so the session timer already represents the whole session — the new clear timer is a genuinely distinct, shorter span. There is at most one `/clear` marker per transcript (a second clear forks again).

## Goals / Non-Goals

**Goals:**
- Add a "since last `/clear`" timer to the wide elapsed cell, leftmost, with a distinguishing glyph + accent colour.
- Preserve fresh-session rendering byte-identically (no `/clear` ⇒ exactly today's output).
- Degrade both → clear-only → shed, with path protection as the outermost guard.
- Bounded, cheap detection that never full-scans the transcript.

**Non-Goals:**
- No change to narrow/medium layouts (they have no timer).
- No new border divider/elbow — both timers share the existing single cell divider.
- No reconstruction of a multi-file clear lineage; the session timer stays `total_duration_ms` as-is.
- No config flag to toggle the feature (out of scope for this change).

## Decisions

**Detection — bounded head-scan.** New reader under `info/` (e.g. `info/clear.py`) opens the transcript, iterates with a hard cap of 30 lines, cheap pre-filters (`'/clear' in ln and 'command-name' in ln`), JSON-parses candidates, and returns the first marker's `timestamp` parsed to epoch (reusing the `Z`→`+00:00` / `datetime.fromisoformat` idiom from `transcript.py`). Early-exit on first match; no match within budget, empty/missing path, or any parse error ⇒ `None`. Rationale: at most one marker exists and it sits at the top, so a 30-line cap is complete in practice and keeps cost O(30 lines) every render even on huge transcripts.

**Gather seam.** Expose as a `@cached_property` on `SessionView` in `info/__init__.py` (e.g. `clear_epoch: float | None`), constructed from the new reader. Formatting stays out of the gather layer; the renderer/layout formats `_fmt_elapsed_clock(max(0, (now − clear_epoch)) * 1000)` using `view.now` for clock-skew safety.

**Display — single cell, two timers.** `elapsed_section` is extended to accept the optional clear-timer string and compose: `<glyph> <accent>CLEAR</accent>  <grey>SESSION</grey>`, clear-first. It returns the rendered content plus its visible width, as today. A new glyph constant goes in `constants.py` (my pick, e.g. nf-md-refresh `\U000f0450`, tuned in `make demo`); accent colour drawn from the existing non-grey palette (`CLR_GREEN_OK` / `CLR_CYAN` / `CLR_PEACH`). The session timer keeps its 8-column right-justified field so its divider column is stable.

**Degradation ladder in `build_wide`.** Compute the both-timers content width and the clear-only content width. Apply the existing `(width - 4) - vsep_w - <cell_w> - helper_w - cache_section_w - right_w >= 5` test (path protection) against the both-width first; if it fails, retry with the clear-only width; if that also fails, shed the cell (`elapsed_section_w = 0`), exactly as today. Fresh session (no `clear_epoch`) ⇒ original single-timer path, unchanged. Only the chosen content string and its width change — `elapsed_div_col`, the vsep, and the elbow threading are untouched.

**Tests.** `test_info.py` for the reader (cleared / fresh / bounded / malformed) and the `SessionView` cached_property; `test_model_section.py` (or the elapsed-section test home) for `elapsed_section` composing one vs two timers and the clock formatting; `test_layout_seam.py` for the degradation ladder (both / clear-only / shed) via an injected `SessionView`. Width assertions go through `_visible_width`.

## Risks / Trade-offs

- **Head-scan cap could miss a deeply-buried marker.** Mitigation: observed markers are always ~line 3; 30 lines is generous. If a future Claude Code layout pushes it lower, the timer silently falls back to "fresh session" (safe degradation, no crash). The cap is a named constant, easy to raise.
- **Semantic mismatch:** session timer is `total_duration_ms` (active-ish) while the clear timer is pure wall-clock. Accepted — "time since last /clear" reads naturally as wall-clock, and the user confirmed the two should differ.
- **Glyph round-trip hazard.** The new PUA glyph is added as an escaped constant in `constants.py` per the repo's PUA rule; never embedded as a raw literal in edited lines.
- **Width pressure:** at mid-wide widths the second timer competes with path/helper/cache. The ladder explicitly prefers the clear timer and falls back cleanly, so the box never overruns or detaches its elbow.
