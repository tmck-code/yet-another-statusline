---
name: yas-pr
description: Assemble a pull request that follows this repo's PR template, then open it as a draft. Use when the user wants to open, create, submit, or raise a PR for the current branch.
---

# YAS PR

Fill in this repo's PR template from the current branch, then open a draft PR. Do not invent
the template structure — read it from the repo so the two never drift.

## Steps

1. **Sanity-check the branch and hooks.** Confirm the current branch is not `main` and has
   commits ahead of `origin/main`. If it's `main` or has no diff, stop and tell the user. Also
   check `git config --local --get core.hooksPath`; if it isn't `.github/hooks`, offer to run
   `make hooks` so the contributor gets pre-commit checks (don't enable it without their yes).

2. **Read the template.** Load `.github/pull_request_template.md`. This is the single source of
   truth for the section structure — mirror its headings exactly.

3. **Draft Context and Changes.** From `git diff main...HEAD` plus the conversation:
   - **Context** — *why* the change is needed; the higher-level goal/problem. Link the related
     issue/PRD (`.scratch/<feature>/...`) if one exists.
   - **Changes** — *what* changed and *how* it works.
   Present these as a draft for the user to edit; don't fabricate motivation you can't infer.

4. **Embed system info.** Run `make pr-info` and paste its output into the System info fenced
   block verbatim.

5. **Run tests.** Run `uv run pytest`. If green, tick the tests checkbox. If red, show the
   failures and ask the user whether to fix first or proceed. Optionally also run `uv run ruff
   check` and `uv run mypy .` and note results.

6. **Benchmark.** Run `make bench` (times this branch vs `main` via a throwaway git worktree).
   If `hyperfine` is not on PATH, `bench.py` prints an install hint and falls back to a Python
   timer — before letting it fall back, offer to install hyperfine (`apt`/`brew`/`cargo`) and ask
   the user; only fall back if they decline. Paste the paste-ready table into the Benchmark
   block. Tick "N/A — no performance-relevant change" instead only for docs/config-only PRs.

7. **Before/after renders.** `gh` can't attach images, so for any rendering change embed
   ANSI-stripped text renders in place of screenshots, via the **yas-demo-text** skill. Render
   in the **`github` glyph mode** (`YAS_GLYPH_MODE=github`) so the embedded snapshot is
   paste-safe in GitHub markdown — it folds the box-drawing frame, block/sparkline ramp, and
   Nerd Font PUA icons to width-1 EAW-narrow/ASCII stand-ins, so the render stays a clean
   rectangle in the browser instead of drifting into ragged edges and PUA boxes. Capture the
   branch ("after") and `main` ("before") snapshots as plain text, then paste each into a
   fenced code block in the Changes section:

   ```bash
   # after — this branch, paste-safe github glyph mode
   YAS_GLYPH_MODE=github make demo/img && .claude/skills/yas-demo-text/scripts/demo-text.sh && cp -r demo/text /tmp/yas-after
   # before — main, rendered in a throwaway worktree
   git worktree add -q /tmp/yas-base main
   ( cd /tmp/yas-base && YAS_GLYPH_MODE=github make demo/img && .claude/skills/yas-demo-text/scripts/demo-text.sh )
   diff -u /tmp/yas-base/demo/text/kitchen-sink.txt /tmp/yas-after/demo/text/kitchen-sink.txt
   git worktree remove /tmp/yas-base
   ```

   With `github` mode the box-drawing layout stays aligned and box-free in the browser, so
   reviewers see the change inline with no web-UI image drag. Scope to one snapshot with
   `DEMO_ONLY=<scenario>`. Dragging real Nerd-Font screenshots into the web UI is still fine if
   the exact icon glyphs matter; github-mode text is the default.

   **Caveat:** `YAS_GLYPH_MODE=github` only renders correctly on a tree that has the `github`
   mode. On a `main` (or base) that predates it, the unknown value falls back to `nerdfont`, so
   the "before" snapshot will still show PUA boxes — which is itself a useful before/after for
   the PR that introduces the mode. Once `github` is on the base branch, both sides render in it
   and the diff is purely the content change.

8. **Confirm, then create the draft.** Show the fully assembled body. After the user confirms,
   run `gh pr create --draft` with that body. Print the PR URL and tell the user to add
   screenshots and click "Ready for review" when done.

## Notes

- Keep checkbox N/A escapes honest — only tick "N/A — no behaviour change" / "N/A — no visible
  change" when that's actually true.
- `gh pr create --draft` is an outward-facing action: never run it before the user confirms the
  body.
