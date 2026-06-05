#!/usr/bin/env bash
# yet-another-statusline — install / wire script
#
# Modes:
#   full      — register marketplace, install/update the yas plugin, then wire
#               settings.json. Requires: claude, curl, jq, Python 3.10+.
#   wire-only — skip the plugin-manager steps and only write settings.json.
#               Requires: jq, Python 3.10+.
#
# Mode is auto-detected from the environment:
#   CLAUDE_PLUGIN_ROOT set   → wire-only (plugin already installed by the host)
#   CLAUDE_PLUGIN_ROOT unset → full
# Override with --wire-only / --full.
#
# Usage:
#   bash ops/install.sh [--wire-only|--full] [--dry-run] [--main]

# NOTE: -e is intentionally omitted. Several probe commands below are expected
# to return non-zero (e.g. `command -v`, jq key-presence checks); using -e
# would abort on them rather than letting the script branch.
set -uo pipefail

# Arg / env parsing -----------------------------
WIRE_ONLY_FLAG=0
FULL_FLAG=0
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --wire-only) WIRE_ONLY_FLAG=1 ;;
        --full)      FULL_FLAG=1      ;;
        --dry-run)   DRY_RUN=1        ;;
        --main)      ;;  # reserved — accept silently, no behaviour change
        *)
            printf "! unknown argument: %s\n" "$arg"
            exit 1
            ;;
    esac
done

# Determine mode
if   [ "$FULL_FLAG"      = "1" ]; then MODE="full"
elif [ "$WIRE_ONLY_FLAG" = "1" ]; then MODE="wire-only"
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then MODE="wire-only"
else MODE="full"
fi

CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

# Python 3.10+ detection ------------------------
# — reused by preflight and do_wire

find_python() {
    for candidate in python python3; do
        local bin
        bin=$(command -v "$candidate" 2>/dev/null) || continue
        local version
        version=$("$bin" --version 2>&1) || continue
        echo "$version" | grep -qE "Python 3\.(1[0-9]|[2-9][0-9])" && { echo "$bin"; return 0; }
    done
    return 1
}

# Preflight checks ------------------------------

preflight_full() {
    for tool in claude curl jq; do
        command -v "$tool" > /dev/null 2>&1 && continue
        case "$tool" in
            claude) printf "! claude not found — install from https://claude.ai/download and re-run\n" ;;
            curl)   printf "! curl not found — install from https://curl.se and re-run\n" ;;
            jq)     printf "! jq not found — install from https://jqlang.github.io/jq and re-run\n" ;;
        esac
        exit 1
    done
    find_python > /dev/null || { printf "! Python 3.10+ not found — install Python 3.10+ and re-run\n"; exit 1; }
}

preflight_wire_only() {
    command -v jq > /dev/null 2>&1 || { printf "! jq not found — install from https://jqlang.github.io/jq and re-run\n"; exit 1; }
    find_python > /dev/null         || { printf "! Python 3.10+ not found — install Python 3.10+ and re-run\n"; exit 1; }
}

# ensure_marketplace (full mode only)
#
# claude plugin marketplace add` and `claude plugin install`
# are designed for scripted/CI use and are expected to run non-interactively
# under a piped (non-TTY) stdin.
# If they prompt in practice, use the manual path:
# ```
# claude plugin marketplace add tmck-code/yet-another-statusline
# claude plugin install yas@yet-another-statusline
# /yas:init
# ```

ensure_marketplace() {
    local present
    present=$(jq -r 'has("yet-another-statusline")' \
        "$CLAUDE_CONFIG_DIR/plugins/known_marketplaces.json" 2>/dev/null) || present="false"

    if [ "$present" = "true" ]; then
        printf "  Marketplace already present — skipping.\n"
        return
    fi

    if [ "$DRY_RUN" = "1" ]; then
        printf "  Would add marketplace: tmck-code/yet-another-statusline\n"
    else
        printf "  Adding marketplace…\n"
        claude plugin marketplace add tmck-code/yet-another-statusline
    fi
}

# ensure_plugin (full mode only) ----------------
ensure_plugin() {
    local present
    present=$(jq -r 'has("yas@yet-another-statusline")' \
        "$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json" 2>/dev/null) || present="false"

    if [ "$present" = "false" ]; then
        if [ "$DRY_RUN" = "1" ]; then
            printf "  Would install: yas@yet-another-statusline\n"
        else
            printf "  Installing yas plugin…\n"
            claude plugin install yas@yet-another-statusline --scope user
        fi
    else
        if [ "$DRY_RUN" = "1" ]; then
            printf "  Would update: yas@yet-another-statusline\n"
        else
            printf "  Updating yas plugin…\n"
            claude plugin update yas@yet-another-statusline --scope user
        fi
    fi
}

# do_wire ---------------------------------------
# — discover renderer
# - clean up legacy files
# - patch settings.json
do_wire() {
    local PLUGIN_ROOT=""
    local SCRIPT=""
    local SETTINGS="$CLAUDE_CONFIG_DIR/settings.json"

    # Renderer discovery
    if [ "$MODE" = "wire-only" ]; then
        PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
        if [ -z "$PLUGIN_ROOT" ]; then
            printf "! CLAUDE_PLUGIN_ROOT is not set — cannot determine plugin root in wire-only mode\n"
            exit 1
        fi
        if [ ! -f "$PLUGIN_ROOT/claude/statusline_command.py" ]; then
            printf "! statusline_command.py not found under CLAUDE_PLUGIN_ROOT: %s\n" "$PLUGIN_ROOT"
            exit 1
        fi
    else
        # Full mode: prefer installed_plugins.json, fall back to cache scan

        # From installed_plugins.json
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

        # Fallback: cache scan
        if [ -z "$PLUGIN_ROOT" ]; then
            PLUGIN_ROOT=$(find "$CLAUDE_CONFIG_DIR/plugins/cache" -maxdepth 5 -name "plugin.json" -print0 2>/dev/null \
                    | xargs -0 grep -l '"name"[[:space:]]*:[[:space:]]*"yas"' 2>/dev/null \
                    | while IFS= read -r f; do
                        dir=$(dirname "$(dirname "$f")")
                        [ -f "$dir/.orphaned_at" ] && continue
                        [ -f "$dir/claude/statusline_command.py" ] && echo "$dir"
                      done \
                    | sort -Vr | head -1)
        fi

        if [ -z "$PLUGIN_ROOT" ]; then
            printf "! yas plugin not found — install first:\n"
            printf "    claude plugin marketplace add tmck-code/yet-another-statusline\n"
            printf "    claude plugin install yas@yet-another-statusline\n"
            exit 1
        fi
    fi

    SCRIPT="$PLUGIN_ROOT/claude/statusline_command.py"
    printf "  Plugin root: %s\n" "$PLUGIN_ROOT"

    # Legacy cleanup
    for f in "$CLAUDE_CONFIG_DIR"/statusline-info-*; do
        [ -e "$f" ] || continue
        rm -f "$f" && printf "  Removed legacy %s\n" "$(basename "$f")"
    done

    # Python detection
    local PYTHON_BIN
    PYTHON_BIN=$(find_python) || { printf "! Python 3.10+ not found — install Python 3.10+ and re-run\n"; exit 1; }
    printf "  Python: %s\n" "$PYTHON_BIN"

    # Exact-match skip
    local NEW_CMD OLD_CMD
    NEW_CMD="\"$PYTHON_BIN\" \"$SCRIPT\""
    OLD_CMD=$(jq -r '.statusLine.command // ""' "$SETTINGS" 2>/dev/null || printf '')
    if [ "$OLD_CMD" = "$NEW_CMD" ]; then
        printf "  statusLine already set to current version — skipping.\n"
        exit 0
    fi

    # dry-run wiring
    if [ "$DRY_RUN" = "1" ]; then
        printf "  Would wire statusLine.command → %s\n" "$NEW_CMD"
        exit 0
    fi

    # Atomic write with backup / validate / restore
    local BAK=""
    if [ ! -f "$SETTINGS" ]; then
        printf '{}\n' > "$SETTINGS"
        printf "  Created %s\n" "$SETTINGS"
    else
        BAK="${SETTINGS}.bak-yas-$(date -u +%Y%m%dT%H%M%SZ)"
        cp "$SETTINGS" "$BAK"
        printf "  Backed up → %s\n" "$(basename "$BAK")"
    fi

    local _result
    if ! _result=$(jq --arg cmd "$NEW_CMD" \
        '.statusLine = {"async":true,"command":$cmd,"refreshInterval":1,"type":"command"}' \
        "$SETTINGS") || [ -z "$_result" ]; then
        printf "! jq failed — settings.json unchanged\n"; exit 1
    fi

    local _tmp
    _tmp=$(mktemp "${SETTINGS}.XXXXXXXXXX")
    printf '%s\n' "$_result" > "$_tmp" || { rm -f "$_tmp"; printf "! write failed — settings.json unchanged\n"; exit 1; }
    mv "$_tmp" "$SETTINGS"

    if ! jq empty "$SETTINGS" 2>/dev/null; then
        printf "! settings.json invalid after write — restoring backup\n"
        [ -n "$BAK" ] && cp "$BAK" "$SETTINGS"
        exit 1
    fi

    [ -n "$OLD_CMD" ] && [ "$OLD_CMD" != "$NEW_CMD" ] && printf "  Replaced stale path: %s\n" "$OLD_CMD"
    printf "  statusLine set → %s\n" "$NEW_CMD"
    printf "  Config dir: %s\n" "$CLAUDE_CONFIG_DIR"
    printf "  Done. Reload Claude Code to activate the statusline.\n"
}

main() {
    if [ "$MODE" = "full" ]; then
        preflight_full
        ensure_marketplace
        ensure_plugin
    else
        preflight_wire_only
    fi
    do_wire
}
main
