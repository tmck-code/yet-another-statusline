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
     issue/PRD (`.scratch/<feature>/...`) if one exists. If this PR bumps the version (step 8),
     reference the new version number here.
   - **Changes** — *what* changed and *how* it works. Group related changes and give each group
     its own `###` (H3) heading. Under each heading, break the distinct points out into bullet
     points rather than one long run-on sentence — a wall of text is hard to read.
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

7. **Before/after screenshots.** For any visible rendering/layout/glyph change, fill the
   **Screenshots / recording** section by **delegating to the `pr-screenshotter` agent**. It
   picks the demo scenarios the diff actually exercises (always kitchen-sink, plus width/justify/
   labels/theme/scenario variants), renders before (`main`) and after (this branch) PNGs,
   publishes them to `tmck-code/yas-pr-screenshots`, and returns a ready-to-paste markdown
   before/after table. Drop that table **verbatim** into the Screenshots / recording section.

   - Don't render or push images yourself — that's the agent's whole job; you just place the
     table it returns.
   - If the change isn't visible (logic/docs/config-only), skip this and tick the section's
     "N/A — no visible change" escape honestly.
   - The agent commits + pushes to the screenshots repo's `main`; flag that to the user when you
     present the body, since it's an outward-facing side effect of this PR flow.

8. **Bump the version (only if the statusline's behaviour changed).** If the diff changes the
   statusline tool or its behaviour — anything a user would notice (rendering, layout, glyphs,
   config knobs, new stats, output format) — bump the version before creating the PR. Work out
   the next version from the current one (`uv version --short`) per semver, then run
   `VERSION=0.X.Y make version/bump`. This is an outward-facing action — it commits **and pushes**
   the bump (`plugin.json`, `pyproject.toml`, `uv.lock`) — so confirm the new number with the user
   before running it. Then reference the new version in the Context section.

   - Skip the bump for developer-only changes that users never see: tests, the Makefile, hooks,
     CI, dev deps, docs, OpenSpec specs, etc. When in doubt about whether a change is user-facing,
     ask rather than bumping blindly.

9. **Confirm, then create the draft.** Show the fully assembled body (Screenshots section already
   populated with the agent's table). After the user confirms, run `gh pr create --draft` with
   that body. Print the PR URL and tell the user to click "Ready for review" when done.

## Notes

- Keep checkbox N/A escapes honest — only tick "N/A — no behaviour change" / "N/A — no visible
  change" when that's actually true.
- `gh pr create --draft` is an outward-facing action: never run it before the user confirms the
  body.
