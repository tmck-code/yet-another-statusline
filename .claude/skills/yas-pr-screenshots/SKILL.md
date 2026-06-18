---
name: yas-pr-screenshots
description: Generate before/after PNG screenshots for a YAS branch's rendering changes, push them to the yas-pr-screenshots repo, and hand back a markdown before/after table for the PR description. Use when the user wants real image screenshots (not ANSI-stripped text) attached to a YAS pull request, or asks to shoot/capture before-after statusline screenshots for a branch.
---

# YAS PR screenshots

Render the statusline on `main` ("before") and on the current branch ("after") as
deterministic PNGs, publish them to the public `tmck-code/yas-pr-screenshots` repo,
and emit a markdown table that another worker (e.g. the **yas-pr** skill or a
`gh pr edit`) drops into the PR body. PNGs come from `DEMO_ONLY=<scenario> make
demo/img` (via `ops/ansi_png.py` — needs ImageMagick `magick` + a Mono Nerd Font).

## Steps

1. **Resolve `<pr_id>`.** If the current branch already has a PR, use its number
   (`gh pr view --json number -q .number`). Otherwise predict the next one:
   `gh pr list --state all --limit 1 --json number -q '.[0].number'` **+ 1**.

2. **Locate the screenshots checkout.** Use `$YAS_PR_SCREENSHOTS_DIR` if set, else a
   sibling `../yas-pr-screenshots`, else clone `git@github.com:tmck-code/yas-pr-screenshots.git`.
   Ensure it's on `main` and clean (`git -C <dir> pull --ff-only`). `*.png` is LFS-tracked there.

3. **Pick variants.** Always shoot `kitchen-sink`. Then read `git diff --stat main...HEAD`
   (and the diff) and add the variants most relevant to what changed — map area → variant:

   | Branch touches | Add variant `LABEL:SCENARIO:ENV` |
   |---|---|
   | subagents / openspec / tasks / workflows | `subagents:subagents:` · `openspec:openspec:` · `tasks:tasks:` · `workflows:workflows:` |
   | context fill / soft limit / token window | `full-context:full-context:` (or `YAS_SOFT_LIMIT=`) |
   | config parsing / errors | `config-error:config-error:` |
   | narrow width / truncation | `narrow:kitchen-sink:YAS_MAX_WIDTH=40` |
   | full width | `full-width:kitchen-sink:YAS_FULL_WIDTH=1` |
   | justify / labels | `justify:kitchen-sink:YAS_JUSTIFY=1` · `labels:kitchen-sink:YAS_LABELS=1` |
   | theme / gradient / colour | `theme-<name>:kitchen-sink:YAS_THEME=<name>` |
   | glyph mode | `github:kitchen-sink:YAS_GLYPH_MODE=github` |
   | model / thinking | `opus-thinking:opus-thinking:` · `sonnet-thinking:sonnet-thinking:` |

   Use the same ENV on both sides so the diff is purely the content change. Scenario
   names: `ops/demo.py` `SCENARIOS` (kitchen-sink, tasks, openspec, subagents, workflows,
   full-context, config-error, sonnet-thinking, opus-thinking, …).

4. **Render + stage.** From the YAS repo root run the helper with the chosen variants:

   ```bash
   .claude/skills/yas-pr-screenshots/scripts/shoot.sh <pr_id> <screenshots_dir> \
     'kitchen-sink:kitchen-sink:' 'narrow:kitchen-sink:YAS_MAX_WIDTH=40' 'subagents:subagents:'
   ```

   It renders after (current tree) and before (a throwaway `main` worktree) for each
   variant, copies them to `screenshots/<pr_id>/{before,after}/<label>.png`, and prints
   the markdown table to stdout. A before render that fails (scenario new to the branch)
   yields an empty before cell instead of aborting.

5. **Commit + push** (outward-facing — confirm with the user first):

   ```bash
   git -C <dir> add screenshots/<pr_id>
   git -C <dir> commit -m "screenshots: PR #<pr_id> before/after (<branch>)"
   git -C <dir> push origin main
   ```

6. **Hand off the table.** Output the table from step 4 verbatim as the final result so
   the PR-authoring worker can paste it into the **Screenshots / recording** section. Do
   **not** edit the PR body yourself — that's the next worker's job.

## Notes

- Images render only after the push lands (GitHub's LFS/image proxy may lag a few seconds).
- The embed URL is `.../blob/main/screenshots/<pr_id>/<side>/<label>.png?raw=true` — the
  `?raw=true` blob form resolves LFS pointers correctly where `raw.githubusercontent.com` doesn't.
- Prerequisite: `magick` on PATH and a Mono Nerd Font installed (see `ops/ansi_png.py` env knobs).
- Want a row label column? Prepend `| variant |` cells — the requested base format is two columns.
