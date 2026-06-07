## Context

The wish is a `/context`-style breakdown of the context window by source
(system prompt, tool/MCP definitions, plugins, skills, memory, messages). This
document captures why that is not currently feasible and what is.

### What the data actually contains

**stdin payload** (`ops/session-info-example.json`, `ContextWindow` in
`session.py`): `total_input_tokens`, `total_output_tokens`,
`context_window_size`, `used_percentage`, `remaining_percentage`, and a single
`current_usage` of `input_tokens` / `output_tokens` /
`cache_creation_input_tokens` / `cache_read_input_tokens`. There is **no
per-source split**.

**transcript jsonl**: assistant messages carry `usage` (the same four token
buckets) plus `attributionPlugin` / `attributionSkill`. Sampling real
transcripts shows these tag *which skill/plugin was active when a message was
generated* (e.g. `attributionSkill: "grill-me"`), i.e. they attribute a turn's
token spend to a skill — **not** the composition of the system prompt. `/context`
itself is computed inside Claude Code by tokenizing the assembled system-prompt
sections; that assembled text and tokenizer are not exposed to the statusline.

## Goals / Non-Goals

**Goals:**
- Document the data gap definitively so it is not silently re-attempted.
- Record the derivable alternatives for a future change.

**Non-Goals:**
- Implementing any breakdown in this change.
- Shipping an approximate breakdown that would misrepresent context composition.

## Decisions

- **Defer.** Do not implement a system/plugins/skills breakdown; it would
  require a tokenizer plus the assembled system prompt, neither of which Claude
  Code exposes to a statusline.
- **Record feasible alternatives** (each a candidate for a separate future
  change):
  - **Per-skill/plugin attribution:** sum transcript `usage` grouped by
    `attributionSkill` / `attributionPlugin`. Answers "where did my tokens go"
    (cumulative spend), not "what occupies context now". Requires a transcript
    scan (the existing `TranscriptUsage` reader already walks the file).
  - **Cache-base vs fresh split:** from `current_usage`, show `cache_read` as the
    stable cached base vs `input` (fresh) vs `output`. Structural, not by-source;
    derivable from stdin alone with no transcript scan.

## Risks / Trade-offs

- **Misleading approximation risk:** attributing the *fixed* system/tool prompt
  to skills via per-message attribution would conflate "turn spend" with
  "context occupancy" and mislead users — the reason the literal breakdown is
  declined rather than approximated.
- **Staleness:** if Claude Code later exposes a `/context`-style breakdown in the
  statusline payload, this deferral should be revisited; the constraint is
  data-availability, not desirability.
