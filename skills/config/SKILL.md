---
name: config
description: "Reconfigure yet-another-statusline — re-runs the interactive install wizard (glyph mode, theme, labels, token soft-limit, and Python version) against the already-installed plugin and re-wires settings.json, without re-registering the marketplace or reinstalling the plugin. Use to switch theme/glyph mode, toggle labels, change the soft limit, or move to Python 3.15 later."
allowed-tools: Bash
effort: low
model: haiku
---

<objective>

Re-run the yet-another-statusline configuration wizard against the
already-installed plugin. The wizard prompts for glyph mode, theme, labels, and
token soft-limit (with live render previews), asks whether to use Python 3.15,
writes `$CLAUDE_CONFIG_DIR/yas.toml`, and re-wires `statusLine.command`.

It does NOT register the marketplace or install/update the plugin — those are
the job of `/yas:init` and the install script's full mode.

</objective>

<workflow>

```bash
bash "${CLAUDE_PLUGIN_ROOT}/ops/install.sh" --reconfigure
```

</workflow>
