# CLAUDE.md — YAS working agreement for Claude Code

This file is read by the **main thread** every session. Its job is to keep the
main context clean by routing work to subagents instead of absorbing it.

## The main thread is a coordinator, not a worker

Your default posture is to **route**, not to perform. Discovery sweeps, test
output, and debug iteration are the things that silently fill the context
window — keep them off the main thread. You absorb summaries and verdicts; the
subagents absorb the noise.

The agents that exist for this (see `.claude/agents/`):

- **`verifier`** — runs the test + demo gates, returns a compact verdict
  (pass/fail counts, failing node ids, one-line root-cause). Read-only.
- **`yas-editor`** — edits the renderer/layout/glyph code and its tests under
  `claude/**` + `test/**`.
- **`spec-implementer`** — implements one named OpenSpec change end-to-end.
- **`spec-author`** — authors a new OpenSpec change (proposal/design/deltas/tasks).
- **`Explore`** — read-only multi-file/-directory search; returns conclusions.

## Hard rules (not suggestions)

1. **Never run the gates on the main thread.** `make test` / `uv run pytest` /
   `make demo/img` go to **`verifier`**. It returns a one-screen verdict and
   never dumps raw output into your context.

2. **A failing gate is a delegation trigger, not a debug trigger.** When
   `verifier` reports a failure, do **not** start reading source, forming
   hypotheses, or editing inline. Take its diagnosis, hand the fix to
   **`yas-editor`** (or `spec-implementer`), then send it back to `verifier` to
   re-check. Loop *editor ↔ verifier* until green — that whole loop stays off
   the main thread.

3. **Multi-file discovery goes to `Explore`**, not inline Grep/Read sweeps.
   Inline `Read` is only for a single known file you are about to discuss or
   quote. If you're about to grep across the tree "to understand X", delegate it.

4. **After a subagent returns, the default is to delegate the NEXT unit of work
   too** — not to absorb it because "I'm already here." Before doing any code or
   debugging yourself, stop and ask: *is this a fresh unit of work that should
   be a subagent?* If yes (almost always, for editing or debugging), delegate.

5. **Parallelise independent work.** When two units don't depend on each other,
   spawn both subagents in a single message so they run concurrently.

## What the main thread *does* do directly

- Decide *what* to do and *which* agent to route it to.
- Hold the plan and the running summary of verdicts.
- Talk to the user, ask clarifying questions, make judgement calls.
- Trivial one-line edits where spinning up an agent costs more than it saves —
  but a *failing test* is never trivial: that's rule 2.

## Gates (for reference — run them via `verifier`, not here)

- Tests: `make test` → `uv run pytest -q`. Subset first, full once before green.
- Lint: `uv run ruff check`.
- Visual gate (renderer/layout/glyph changes): `make demo/img` then
  `.claude/skills/yas-demo-text/scripts/demo-text.sh`, diff the `demo/text/*.txt`.

For renderer/layout/glyph work, the relevant invariants live in the
**`tmck-code-statusline`** skill — the usual failure class is column-width math
around invisible PUA glyphs, caught by the demo gate rather than pytest.
