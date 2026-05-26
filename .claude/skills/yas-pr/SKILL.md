---
name: yas-pr
description: Assemble a pull request that follows this repo's PR template, then open it as a draft. Use when the user wants to open, create, submit, or raise a PR for the current branch.
---

# YAS PR

Fill in this repo's PR template from the current branch, then open a draft PR. Do not invent
the template structure — read it from the repo so the two never drift.

## Steps

1. **Sanity-check the branch.** Confirm the current branch is not `main` and has commits ahead
   of `origin/main`. If it's `main` or has no diff, stop and tell the user.

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

7. **Screenshots.** You cannot attach images via `gh`. Remind the user that for any rendering
   change they should drag before/after images into the draft's web UI before marking it ready.
   For rendering changes, `make demo/img` can produce snapshots to use.

8. **Confirm, then create the draft.** Show the fully assembled body. After the user confirms,
   run `gh pr create --draft` with that body. Print the PR URL and tell the user to add
   screenshots and click "Ready for review" when done.

## Notes

- Keep checkbox N/A escapes honest — only tick "N/A — no behaviour change" / "N/A — no visible
  change" when that's actually true.
- `gh pr create --draft` is an outward-facing action: never run it before the user confirms the
  body.
