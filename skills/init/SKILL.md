---
name: init
description: "Wire yet-another-statusline into Claude Code — writes statusLine.command to settings.json in CLAUDE_CONFIG_DIR (default ~/.claude/). Run once after plugin install, and again after every upgrade to update the versioned path."
allowed-tools: Bash
effort: low
model: haiku
---

<objective>

Write `statusLine.command` into `settings.json` (in `$CLAUDE_CONFIG_DIR`, defaulting to `~/.claude/`) pointing at the newest installed version of this plugin's Python renderer.

Run once after `claude plugin install yas@yet-another-statusline`.
Re-run after every upgrade — it detects a stale versioned path and rewrites it.

</objective>

<workflow>

```bash
bash "${CLAUDE_PLUGIN_ROOT}/ops/install.sh"
```

</workflow>
