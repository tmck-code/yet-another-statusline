---
name: init
description: "Wire yet-another-statusline into Claude Code — writes statusLine.command to settings.json in CLAUDE_CONFIG_DIR (default ~/.claude/). Run once after plugin install, and again after every upgrade to update the versioned path."
allowed-tools: Read, Write, Bash
effort: low
model: haiku
---

<objective>

Write `statusLine.command` into `settings.json` (in `$CLAUDE_CONFIG_DIR`, defaulting to `~/.claude/`) pointing at this plugin's Python renderer.

Run once after `claude plugin install yas@yet-another-statusline`.
Re-run after every upgrade — detects stale versioned path and rewrites.

</objective>

<workflow>

## Step 1: Locate plugin root

```bash
CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

PLUGIN_ROOT=$(jq -r '
    .plugins
    | to_entries[]
    | select(.key | ascii_downcase | contains("yas"))
    | .value[]
    | select(.installPath != null)
    | [.installedAt, .installPath]
    | @tsv
' "$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json" 2>/dev/null \
    | sort -rk1 | head -1 | cut -f2)  # timeout: 5000

if [ -z "$PLUGIN_ROOT" ]; then
    PLUGIN_ROOT=$(find "$CLAUDE_CONFIG_DIR/plugins/cache" -maxdepth 5 -name "plugin.json" 2>/dev/null \
            | xargs grep -l '"name"[[:space:]]*:[[:space:]]*"yas"' 2>/dev/null \
            | while IFS= read -r f; do
                dir=$(dirname "$(dirname "$f")")
                [ -f "$dir/.orphaned_at" ] && continue
                echo "$dir"
              done \
            | sort -Vr | head -1)  # timeout: 10000
fi

if [ -z "$PLUGIN_ROOT" ]; then
    printf "! yas plugin not found — install first:\n    claude plugin marketplace add tmck-code/yet-another-statusline\n    claude plugin install yas@yet-another-statusline\n"
    exit 1
fi

SCRIPT="$PLUGIN_ROOT/claude/statusline_command.py"
if [ ! -f "$SCRIPT" ]; then
    printf "! statusline_command.py not found at %s\n" "$SCRIPT"
    exit 1
fi

printf "  Plugin root: %s\n" "$PLUGIN_ROOT"
```

## Step 2: Check if already current

```bash
jq --arg script "$SCRIPT" -e '
    (.statusLine.command // "") | contains($script)
' "$CLAUDE_CONFIG_DIR/settings.json" >/dev/null 2>&1  # timeout: 5000
```

If exit 0: print `statusLine already set to current version — skipping.` and stop.

## Step 3: Detect Python interpreter

```bash
PYTHON_BIN=""
for candidate in python python3; do
    bin=$(which "$candidate" 2>/dev/null) || continue
    version=$("$bin" --version 2>&1) || continue
    echo "$version" | grep -qE "Python 3\.(1[0-9]|[2-9][0-9])" && PYTHON_BIN="$bin" && break
done  # timeout: 5000

if [ -z "$PYTHON_BIN" ]; then
    printf "! Python 3.10+ not found — install Python 3.10+ and re-run /yas:init\n"
    exit 1
fi

printf "  Python: %s\n" "$PYTHON_BIN"
```

## Step 4: Back up and write statusLine.command

```bash
SETTINGS="$CLAUDE_CONFIG_DIR/settings.json"

# Create settings.json with empty object if missing (no backup needed for a new file)
if [ ! -f "$SETTINGS" ]; then
    printf '{}\n' > "$SETTINGS"
    printf "  Created %s\n" "$SETTINGS"
else
    BAK_TS=$(date -u +%Y%m%dT%H%M%SZ)
    cp "$SETTINGS" "${SETTINGS}.bak-yas-${BAK_TS}"  # timeout: 5000
    printf "  Backed up → settings.json.bak-yas-%s\n" "$BAK_TS"
fi

_result=$(jq --arg cmd "\"$PYTHON_BIN\" \"$SCRIPT\"" \
    '.statusLine = {"async":true,"command":$cmd,"refreshInterval":1,"type":"command"}' \
    "$SETTINGS")  # timeout: 5000
[ $? -eq 0 ] && [ -n "$_result" ] || { printf "! jq failed — settings.json unchanged\n"; exit 1; }

_tmp=$(mktemp "${SETTINGS}.XXXXXXXXXX")
printf '%s\n' "$_result" > "$_tmp" \
    || { rm -f "$_tmp"; printf "! write failed — settings.json unchanged\n"; exit 1; }
mv "$_tmp" "$SETTINGS"  # timeout: 3000
printf "  settings.json updated\n"
```

## Step 5: Validate and report

```bash
jq empty "$SETTINGS"  # timeout: 5000
```

If invalid: restore backup, report error, stop.

Print:
```
  statusLine set → "$PYTHON_BIN" "$SCRIPT"
  Config dir: $CLAUDE_CONFIG_DIR
  Done. Reload Claude Code to activate the statusline.
```

</workflow>
