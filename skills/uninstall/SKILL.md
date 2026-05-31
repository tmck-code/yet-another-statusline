---
name: uninstall
description: "Unwire yet-another-statusline from Claude Code — removes statusLine.command from settings.json in CLAUDE_CONFIG_DIR (default ~/.claude/) and deletes the renderer's runtime state. Run before (or after) `claude plugin uninstall yas`, which only deletes the plugin cache and leaves the statusLine config behind."
allowed-tools: Read, Write, Bash
effort: low
model: haiku
---

<objective>

Reverse `/yas:init`. Remove the `statusLine` block from `settings.json` in `$CLAUDE_CONFIG_DIR` (default `~/.claude/`), only when it points at this plugin's renderer, and delete the runtime logs and per-session payloads the renderer wrote.

`claude plugin uninstall yas@yet-another-statusline` only deletes the plugin *cache* — Claude Code keeps reading `statusLine.command` from settings.json and tries to run the now-missing script. This skill clears that config so the statusline actually stops.

Leaves untouched: a custom (non-yas) statusLine, the `settings.json.bak-yas-*` backups, the user's `statusline-theme` / `terminal-width` config files, and any `make install` dev symlinks.

</objective>

<workflow>

## Step 0: Resolve config dir

```bash
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CONFIG_DIR/settings.json"
printf "  Config dir: %s\n" "$CONFIG_DIR"
```

## Step 1: Inspect the current statusLine

```bash
if [ ! -f "$SETTINGS" ]; then
    printf "  No settings.json — nothing to unwire.\n"
    CFG_STATE="absent"
else
    CMD=$(jq -r '.statusLine.command // ""' "$SETTINGS" 2>/dev/null)  # timeout: 5000
    if [ -z "$CMD" ]; then
        printf "  No statusLine configured — nothing to remove.\n"
        CFG_STATE="none"
    elif printf '%s' "$CMD" | grep -q "statusline_command.py"; then
        printf "  Found yas statusLine: %s\n" "$CMD"
        CFG_STATE="yas"
    else
        printf "! statusLine points elsewhere — not a yas command:\n    %s\n  Leaving it untouched.\n" "$CMD"
        CFG_STATE="foreign"
    fi
fi
```

`statusline_command.py` is the signature of this project's renderer (used by both the plugin-cache path and the dev checkout path from the README). If `CFG_STATE` is anything other than `yas`, **skip Step 2** — do not edit `statusLine`.

## Step 2: Back up, then remove the statusLine block

Only when `CFG_STATE` is `yas`:

```bash
BAK_TS=$(date -u +%Y%m%dT%H%M%SZ)
cp "$SETTINGS" "$SETTINGS.bak-yas-${BAK_TS}"  # timeout: 5000
printf "  Backed up → settings.json.bak-yas-%s\n" "$BAK_TS"

_result=$(jq 'del(.statusLine)' "$SETTINGS")  # timeout: 5000
[ $? -eq 0 ] && [ -n "$_result" ] || { printf "! jq failed — settings.json unchanged\n"; exit 1; }

_tmp=$(mktemp "$SETTINGS.XXXXXXXXXX")
printf '%s\n' "$_result" > "$_tmp" \
    || { rm -f "$_tmp"; printf "! write failed — settings.json unchanged\n"; exit 1; }
mv "$_tmp" "$SETTINGS"  # timeout: 3000

if jq empty "$SETTINGS" 2>/dev/null; then  # timeout: 5000
    printf "  Removed statusLine from settings.json\n"
else
    cp "$SETTINGS.bak-yas-${BAK_TS}" "$SETTINGS"
    printf "! Result was invalid JSON — restored from backup\n"
    exit 1
fi
```

## Step 3: Delete runtime state

The renderer writes these as it runs. Safe to remove; they regenerate if the statusline is ever reinstalled.

```bash
for f in statusline-tokens.log statusline-token-rate.log; do
    if [ -f "$CONFIG_DIR/$f" ]; then
        rm -f "$CONFIG_DIR/$f" && printf "  Removed %s\n" "$f"
    fi
done

if [ -d "$CONFIG_DIR/statusline-output" ]; then
    rm -rf "$CONFIG_DIR/statusline-output" && printf "  Removed statusline-output/\n"
fi
```

(Use the resolved `$CONFIG_DIR` — not a hardcoded `~/.claude`.)

## Step 4: Report

Count, but do not delete, the init/uninstall backups:

```bash
N_BAK=$(ls -1 "$CONFIG_DIR"/settings.json.bak-yas-* 2>/dev/null | wc -l | tr -d ' ')
[ "$N_BAK" -gt 0 ] && printf "  Kept %s settings.json.bak-yas-* backup(s) in %s\n" "$N_BAK" "$CONFIG_DIR"
```

Then print a summary:

```
  Done. statusLine config and runtime state removed.

  Still installed (this skill does not remove these):
    • the plugin itself — run:  claude plugin uninstall yas@yet-another-statusline
    • your theme/width prefs — statusline-theme, terminal-width
    • backups — settings.json.bak-yas-*  (delete by hand if you want)

  Reload Claude Code to clear the statusline.
```

If `CFG_STATE` was `foreign`, remind the user their custom statusLine was kept on purpose.

</workflow>
