---
name: init
description: "Wire yet-another-statusline into Claude Code — writes statusLine.command to settings.json in CLAUDE_CONFIG_DIR (default ~/.claude/). Run once after plugin install, and again after every upgrade to update the versioned path."
allowed-tools: Read, Write, Bash
effort: low
model: haiku
---

<objective>

Write `statusLine.command` into `settings.json` (in `$CLAUDE_CONFIG_DIR`, defaulting to `~/.claude/`) pointing at the newest installed version of this plugin's Python renderer.

Run once after `claude plugin install yas@yet-another-statusline`.
Re-run after every upgrade — it detects a stale versioned path and rewrites it.

</objective>

<workflow>

Run the **entire** block below as a **single** Bash invocation. It deliberately
relies on shell variables (`$SCRIPT`, `$PYTHON_BIN`, …) set earlier in the same
script — splitting it across calls loses that state and writes a broken command.

```bash
set -u
CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_CONFIG_DIR/settings.json"

# ── 1. Locate the newest installed yas plugin root ──────────────────────────
# Authoritative source: installed_plugins.json. Keep only roots whose renderer
# actually exists on disk (drops orphaned/stale entries), then pick the highest
# version via version-sort — not installedAt, which is the first-install time.
PLUGIN_ROOT=$(jq -r '
    .plugins
    | to_entries[]
    | select(.key | ascii_downcase | contains("yas"))
    | .value[]
    | select(.installPath != null)
    | .installPath
' "$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json" 2>/dev/null \
    | while IFS= read -r d; do
        [ -f "$d/claude/statusline_command.py" ] && echo "$d"
      done \
    | sort -Vr | head -1)

# Fallback: scan the cache for yas plugin.json, skip orphaned dirs, version-sort.
if [ -z "$PLUGIN_ROOT" ]; then
    PLUGIN_ROOT=$(find "$CLAUDE_CONFIG_DIR/plugins/cache" -maxdepth 5 -name "plugin.json" 2>/dev/null \
            | xargs grep -l '"name"[[:space:]]*:[[:space:]]*"yas"' 2>/dev/null \
            | while IFS= read -r f; do
                dir=$(dirname "$(dirname "$f")")
                [ -f "$dir/.orphaned_at" ] && continue
                [ -f "$dir/claude/statusline_command.py" ] && echo "$dir"
              done \
            | sort -Vr | head -1)
fi

if [ -z "$PLUGIN_ROOT" ]; then
    printf "! yas plugin not found — install first:\n    claude plugin marketplace add tmck-code/yet-another-statusline\n    claude plugin install yas@yet-another-statusline\n"
    exit 1
fi

SCRIPT="$PLUGIN_ROOT/claude/statusline_command.py"  # existence already verified above
printf "  Plugin root: %s\n" "$PLUGIN_ROOT"

# ── 2. Remove legacy statusline-info-* files (unconditional) ────────────────
for f in "$CLAUDE_CONFIG_DIR"/statusline-info-*; do
    [ -e "$f" ] || continue
    rm -f "$f" && printf "  Removed legacy %s\n" "$(basename "$f")"
done

# ── 3. Detect a Python 3.10+ interpreter ────────────────────────────────────
PYTHON_BIN=""
for candidate in python python3; do
    bin=$(command -v "$candidate" 2>/dev/null) || continue
    version=$("$bin" --version 2>&1) || continue
    echo "$version" | grep -qE "Python 3\.(1[0-9]|[2-9][0-9])" && PYTHON_BIN="$bin" && break
done
if [ -z "$PYTHON_BIN" ]; then
    printf "! Python 3.10+ not found — install Python 3.10+ and re-run /yas:init\n"
    exit 1
fi
printf "  Python: %s\n" "$PYTHON_BIN"

# ── 4. Skip only on an EXACT match (avoids 0.2.2-vs-0.2.20 substring traps) ──
NEW_CMD="\"$PYTHON_BIN\" \"$SCRIPT\""
OLD_CMD=$(jq -r '.statusLine.command // ""' "$SETTINGS" 2>/dev/null || printf '')
if [ "$OLD_CMD" = "$NEW_CMD" ]; then
    printf "  statusLine already set to current version — skipping.\n"
    exit 0
fi

# ── 5. Back up, then write statusLine.command atomically ────────────────────
if [ ! -f "$SETTINGS" ]; then
    printf '{}\n' > "$SETTINGS"
    printf "  Created %s\n" "$SETTINGS"
    BAK=""
else
    BAK="${SETTINGS}.bak-yas-$(date -u +%Y%m%dT%H%M%SZ)"
    cp "$SETTINGS" "$BAK"
    printf "  Backed up → %s\n" "$(basename "$BAK")"
fi

_result=$(jq --arg cmd "$NEW_CMD" \
    '.statusLine = {"async":true,"command":$cmd,"refreshInterval":1,"type":"command"}' \
    "$SETTINGS")
if [ $? -ne 0 ] || [ -z "$_result" ]; then
    printf "! jq failed — settings.json unchanged\n"; exit 1
fi

_tmp=$(mktemp "${SETTINGS}.XXXXXXXXXX")
printf '%s\n' "$_result" > "$_tmp" || { rm -f "$_tmp"; printf "! write failed — settings.json unchanged\n"; exit 1; }
mv "$_tmp" "$SETTINGS"

# ── 6. Validate; restore the backup on corruption ───────────────────────────
if ! jq empty "$SETTINGS" 2>/dev/null; then
    printf "! settings.json invalid after write — restoring backup\n"
    [ -n "$BAK" ] && cp "$BAK" "$SETTINGS"
    exit 1
fi

[ -n "$OLD_CMD" ] && [ "$OLD_CMD" != "$NEW_CMD" ] && printf "  Replaced stale path: %s\n" "$OLD_CMD"
printf "  statusLine set → %s\n" "$NEW_CMD"
printf "  Config dir: %s\n" "$CLAUDE_CONFIG_DIR"
printf "  Done. Reload Claude Code to activate the statusline.\n"
```

</workflow>
