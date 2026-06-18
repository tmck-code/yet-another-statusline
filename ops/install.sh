#!/usr/bin/env bash
# yet-another-statusline — install / wire / uninstall script
#
# Modes:
#   full      — register marketplace, install/update the yas plugin, then wire
#               settings.json. Requires: claude, curl, jq, Python 3.10+.
#   wire-only — skip the plugin-manager steps and only write settings.json.
#               Requires: jq, Python 3.10+.
#   uninstall — remove statusLine from settings.json and clean up legacy files.
#               With --full, also runs `claude plugin uninstall`. Requires: jq.
#
# Mode is auto-detected from the environment:
#   CLAUDE_PLUGIN_ROOT set   → wire-only (plugin already installed by the host)
#   CLAUDE_PLUGIN_ROOT unset → full
# Override with --wire-only / --full / --uninstall.
#
# Usage:
#   bash ops/install.sh [--wire-only|--full|--uninstall] [--dry-run] [--main]

# NOTE: -e is intentionally omitted. Several probe commands below are expected
# to return non-zero (e.g. `command -v`, jq key-presence checks); using -e
# would abort on them rather than letting the script branch.
set -uo pipefail

# Arg / env parsing -----------------------------
WIRE_ONLY_FLAG=0
FULL_FLAG=0
UNINSTALL_FLAG=0
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --wire-only) WIRE_ONLY_FLAG=1  ;;
        --full)      FULL_FLAG=1       ;;
        --uninstall) UNINSTALL_FLAG=1  ;;
        --dry-run)   DRY_RUN=1         ;;
        --main)      ;;  # reserved — accept silently, no behaviour change
        *)
            printf "! unknown argument: %s\n" "$arg"
            exit 1
            ;;
    esac
done

# Determine mode
if   [ "$UNINSTALL_FLAG" = "1" ]; then MODE="uninstall"
elif [ "$FULL_FLAG"      = "1" ]; then MODE="full"
elif [ "$WIRE_ONLY_FLAG" = "1" ]; then MODE="wire-only"
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then MODE="wire-only"
else MODE="full"
fi

CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

# Python 3.15 provisioning + detection ----------
# — reused by preflight and do_wire

# Where a plugin-local, uv-managed CPython lives (provisioned by provision_python).
yas_python_dir() {
    printf '%s/.python\n' "$1"  # $1 = PLUGIN_ROOT
}

# provision_python PLUGIN_ROOT
# Install (idempotently) a private CPython 3.15 into $PLUGIN_ROOT/.python via uv
# and echo the concrete interpreter binary path. 3.15 is ~6-8 ms faster to start
# than 3.13; 3.14 is *slower* than 3.13, so we pin 3.15 explicitly here.
#
# This keeps the speed win without mutating the user's system Python or PATH:
# the statusline command points straight at this binary (never `uv run`, whose
# per-invocation overhead — the statusline is spawned on every prompt — would
# erase the win).
#
# Returns non-zero if uv is absent or the install/resolve fails (caller falls
# back to find_python).
provision_python() {
    local plugin_root="$1"
    command -v uv > /dev/null 2>&1 || return 1

    local pydir
    pydir=$(yas_python_dir "$plugin_root")

    if [ "$DRY_RUN" = "1" ]; then
        printf "  Would provision private CPython 3.15 → %s (via uv)\n" "$pydir" 1>&2
        # Don't download in dry-run; report a synthetic path so wiring can preview.
        printf '%s/<cpython-3.15>/bin/python3.15\n' "$pydir"
        return 0
    fi

    # Install is idempotent: uv reuses an existing 3.15 in the install dir and,
    # across plugin reinstalls, hydrates from uv's shared download cache (fast).
    UV_PYTHON_INSTALL_DIR="$pydir" uv python install 3.15 > /dev/null 2>&1 || return 1

    # Resolve the concrete binary. Primary: ask uv, scoped to our managed dir.
    local bin
    bin=$(UV_PYTHON_INSTALL_DIR="$pydir" uv python find 3.15 --managed-python 2>/dev/null)
    if [ -z "$bin" ] || [ ! -x "$bin" ]; then
        # Fallback: glob the install dir for the newest 3.15 interpreter.
        # find (not ls) so odd chars in the path are handled; sort -Vr → newest.
        bin=$(find "$pydir" -maxdepth 3 -name python3.15 -path '*/cpython-3.15*/bin/*' 2>/dev/null | sort -Vr | head -1)
    fi
    [ -n "$bin" ] && [ -x "$bin" ] || return 1
    printf '%s\n' "$bin"
}

# find_python — pick a usable system interpreter (>=3.10), avoiding 3.14.
# 3.14 starts up *slower* than 3.13, so when several qualify we prefer any
# non-3.14 (3.13/3.15-class) over a 3.14. Used as the fallback when uv-based
# provisioning is unavailable.
find_python() {
    local fallback=""
    for candidate in python python3 python3.15 python3.13 python3.12 python3.11 python3.10; do
        local bin
        bin=$(command -v "$candidate" 2>/dev/null) || continue
        local version
        version=$("$bin" --version 2>&1) || continue
        # Require >=3.10.
        echo "$version" | grep -qE "Python 3\.(1[0-9]|[2-9][0-9])" || continue
        if echo "$version" | grep -qE "Python 3\.14(\.|$| )"; then
            # 3.14 is slower — only use it if nothing better turns up.
            [ -z "$fallback" ] && fallback="$bin"
            continue
        fi
        echo "$bin"; return 0
    done
    [ -n "$fallback" ] && { echo "$fallback"; return 0; }
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
        if [ "$DRY_RUN" = "1" ]; then
            printf "  Would update marketplace: yet-another-statusline\n"
        else
            printf "  Updating marketplace…\n"
            claude plugin marketplace update yet-another-statusline
        fi
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
    present=$(jq -r '.plugins | has("yas@yet-another-statusline")' \
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

    # Python selection: prefer a private, plugin-local CPython 3.15 provisioned
    # via uv (fastest startup, no system mutation). Fall back to a system
    # interpreter (>=3.10, avoiding 3.14) when uv is unavailable.
    local PYTHON_BIN
    if PYTHON_BIN=$(provision_python "$PLUGIN_ROOT"); then
        printf "  Python: %s (private uv-managed 3.15)\n" "$PYTHON_BIN"
    elif PYTHON_BIN=$(find_python); then
        printf "  Python: %s (system fallback)\n" "$PYTHON_BIN"
    else
        printf "! Python 3.10+ not found — install Python 3.10+ (or uv) and re-run\n"; exit 1
    fi

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
        '.statusLine = {"async":true,"command":$cmd,"refreshInterval":1,"type":"command","padding":1}' \
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

# do_uninstall ---------------------------------
# — remove statusLine from settings.json (atomic, with backup/validate/restore)
# - clean up legacy statusline-info-* files
# - with --full, also uninstall the plugin via `claude plugin uninstall`
do_uninstall() {
    local SETTINGS="$CLAUDE_CONFIG_DIR/settings.json"

    command -v jq > /dev/null 2>&1 || { printf "! jq not found — install from https://jqlang.github.io/jq and re-run\n"; exit 1; }

    # Legacy cleanup (always, even if settings has nothing to remove)
    for f in "$CLAUDE_CONFIG_DIR"/statusline-info-*; do
        [ -e "$f" ] || continue
        if [ "$DRY_RUN" = "1" ]; then
            printf "  Would remove legacy %s\n" "$(basename "$f")"
        else
            rm -f "$f" && printf "  Removed legacy %s\n" "$(basename "$f")"
        fi
    done

    # Remove statusLine key from settings.json
    if [ ! -f "$SETTINGS" ]; then
        printf "  settings.json not found — nothing to unwire.\n"
    else
        local HAS_KEY
        HAS_KEY=$(jq 'has("statusLine")' "$SETTINGS" 2>/dev/null) || HAS_KEY="false"
        if [ "$HAS_KEY" != "true" ]; then
            printf "  statusLine not present in settings.json — nothing to unwire.\n"
        elif [ "$DRY_RUN" = "1" ]; then
            printf "  Would remove statusLine from %s\n" "$SETTINGS"
        else
            local BAK
            BAK="${SETTINGS}.bak-yas-$(date -u +%Y%m%dT%H%M%SZ)"
            cp "$SETTINGS" "$BAK"
            printf "  Backed up → %s\n" "$(basename "$BAK")"

            local _result
            if ! _result=$(jq 'del(.statusLine)' "$SETTINGS") || [ -z "$_result" ]; then
                printf "! jq failed — settings.json unchanged\n"; exit 1
            fi

            local _tmp
            _tmp=$(mktemp "${SETTINGS}.XXXXXXXXXX")
            printf '%s\n' "$_result" > "$_tmp" || { rm -f "$_tmp"; printf "! write failed — settings.json unchanged\n"; exit 1; }
            mv "$_tmp" "$SETTINGS"

            if ! jq empty "$SETTINGS" 2>/dev/null; then
                printf "! settings.json invalid after write — restoring backup\n"
                cp "$BAK" "$SETTINGS"
                exit 1
            fi
            printf "  Removed statusLine from settings.json\n"
        fi
    fi

    # Private uv-managed CPython cleanup (best-effort).
    # Discover the plugin root the same ways do_wire does, then remove its
    # .python dir if present.
    local UN_ROOT=""
    if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "$(yas_python_dir "$CLAUDE_PLUGIN_ROOT")" ]; then
        UN_ROOT="$CLAUDE_PLUGIN_ROOT"
    else
        UN_ROOT=$(jq -r '
            .plugins
            | to_entries[]
            | select(.key | ascii_downcase | contains("yas"))
            | .value[]
            | select(.installPath != null)
            | .installPath
        ' "$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json" 2>/dev/null \
            | while IFS= read -r d; do
                [ -d "$(yas_python_dir "$d")" ] && echo "$d"
              done \
            | head -1)
    fi
    if [ -n "$UN_ROOT" ]; then
        local PYDIR
        PYDIR=$(yas_python_dir "$UN_ROOT")
        if [ -d "$PYDIR" ]; then
            if [ "$DRY_RUN" = "1" ]; then
                printf "  Would remove private CPython dir %s\n" "$PYDIR"
            else
                rm -rf "$PYDIR" && printf "  Removed private CPython dir %s\n" "$PYDIR"
            fi
        fi
    fi

    # Plugin uninstall (--full only)
    if [ "$FULL_FLAG" = "1" ]; then
        command -v claude > /dev/null 2>&1 || { printf "! claude not found — cannot uninstall plugin\n"; exit 1; }
        local present
        present=$(jq -r '.plugins | has("yas@yet-another-statusline")' \
            "$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json" 2>/dev/null) || present="false"
        if [ "$present" != "true" ]; then
            printf "  yas plugin not installed — skipping plugin uninstall.\n"
        elif [ "$DRY_RUN" = "1" ]; then
            printf "  Would uninstall: yas@yet-another-statusline\n"
        else
            printf "  Uninstalling yas plugin…\n"
            claude plugin uninstall yas@yet-another-statusline --scope user
        fi
    fi

    if [ "$DRY_RUN" != "1" ]; then printf "  Done.\n"; fi
}

main() {
    if [ "$MODE" = "uninstall" ]; then
        do_uninstall
    elif [ "$MODE" = "full" ]; then
        preflight_full
        ensure_marketplace
        ensure_plugin
        do_wire
    else
        preflight_wire_only
        do_wire
    fi
}
main
