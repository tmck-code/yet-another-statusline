# .claude/ — Project-level Claude Code config

This directory is for **contributors and developers** working on the YAS codebase.
It is **not** loaded by plugin users — plugin skills live in `skills/` at the repo root.

## Contents

### `skills/tmck-code-statusline/`

Developer skill loaded when Claude Code runs inside this repo.
Covers the layered renderer architecture (GradientEngine / BorderRenderer / Renderer),
PUA glyph hazards, border/elbow column math, and the pre/post-edit checklists.

Use it when touching `claude/statusline_command.py` or related files.

### `settings.local.json` *(gitignored)*

Pre-approves the `/yas:init` skill and common Bash operations for local dev sessions.
Create from scratch or copy from a teammate — it is never committed.

### `state/` *(gitignored)*

Ephemeral session breadcrumbs written by Claude Code hooks. Safe to delete.

## Not for plugin users

When installed via `claude plugin install yas@yet-another-statusline`, Claude Code loads
skills from `skills/init/` (the `/yas:init` skill). This `.claude/` directory is ignored
by the plugin runtime.