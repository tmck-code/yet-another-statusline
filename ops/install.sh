#!/usr/bin/env bash
# yet-another-statusline — install / wire / uninstall script
#
# Modes:
#   full      — register marketplace, install/update the yas plugin, then wire
#               settings.json. Requires: claude, curl, system Python 3.10+.
#   wire-only — skip the plugin-manager steps and only write settings.json.
#               Requires: system Python 3.10+.
#   uninstall — remove statusLine from settings.json and clean up legacy files.
#               With --full, also runs `claude plugin uninstall`.
#
# All JSON is handled through the resolved Python interpreter (see json_py) — the
# script needs no external JSON tool. `uv` is bootstrapped plugin-locally when absent.
#
# Mode is auto-detected from the environment:
#   CLAUDE_PLUGIN_ROOT set   → wire-only (plugin already installed by the host)
#   CLAUDE_PLUGIN_ROOT unset → full
# Override with --wire-only / --full / --uninstall.
#
# Usage:
#   bash ops/install.sh [--wire-only|--full|--uninstall] [--dry-run] [--main]

# NOTE: -e is intentionally omitted. Several probe commands below are expected
# to return non-zero (e.g. `command -v`, json_py key-presence checks); using -e
# would abort on them rather than letting the script branch.
set -uo pipefail

# Arg / env parsing -----------------------------
WIRE_ONLY_FLAG=0
FULL_FLAG=0
UNINSTALL_FLAG=0
RECONFIGURE_FLAG=0
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --wire-only)   WIRE_ONLY_FLAG=1   ;;
        --full)        FULL_FLAG=1        ;;
        --uninstall)   UNINSTALL_FLAG=1   ;;
        --reconfigure) RECONFIGURE_FLAG=1 ;;
        --dry-run)     DRY_RUN=1          ;;
        --main)        ;;  # reserved — accept silently, no behaviour change
        *)
            printf "! unknown argument: %s\n" "$arg"
            exit 1
            ;;
    esac
done

# Determine mode
if   [ "$UNINSTALL_FLAG"   = "1" ]; then MODE="uninstall"
elif [ "$RECONFIGURE_FLAG" = "1" ]; then MODE="reconfigure"
elif [ "$FULL_FLAG"        = "1" ]; then MODE="full"
elif [ "$WIRE_ONLY_FLAG"   = "1" ]; then MODE="wire-only"
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then MODE="wire-only"
else MODE="full"
fi

CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

# Interactivity / TTY gating --------------------
# Interactive is the default. We force non-interactive when YAS_NO_TTY=1 OR no
# readable /dev/tty exists (CI safety — the installer must never block on input).
# --dry-run is a non-mutating preview and likewise issues no prompts, so it never
# blocks even on a real terminal. is_interactive() is safe under `set -u`: every
# env read uses the :- default.
is_interactive() {
    [ "$DRY_RUN" != "1" ] && [ "${YAS_NO_TTY:-}" != "1" ] && [ -r /dev/tty ]
}

if is_interactive; then INTERACTIVE=1; else INTERACTIVE=0; fi

# Color detection + constants ------------------
# _color_on — emit color only when stdout is a tty AND NO_COLOR is unset/empty
# AND $TERM != dumb; OR when YAS_FORCE_COLOR=1 forces it (overriding the not-a-tty
# condition). NO_COLOR always wins: if set non-empty, color is OFF regardless.
# Safe under `set -u`: every env read uses the :- default.
_color_on() {
    [ -n "${NO_COLOR:-}" ] && return 1
    [ "${YAS_FORCE_COLOR:-}" = "1" ] && return 0
    [ -t 1 ] && [ "${TERM:-}" != "dumb" ]
}

# COLOR_DEPTH ∈ {0,1,2,3}: 0 = off, 1 = basic 16-color, 2 = 256-color,
# 3 = truecolor. When color is OFF the depth is 0. An explicit YAS_COLOR_DEPTH
# (none/basic/256/truecolor) overrides detection; otherwise COLORTERM /
# TERM are sniffed. Messages always use 16-color SGR; only the logo is
# depth-keyed.
if _color_on; then
    case "${YAS_COLOR_DEPTH:-}" in
        none)            COLOR_DEPTH=0 ;;
        basic)           COLOR_DEPTH=1 ;;
        256)             COLOR_DEPTH=2 ;;
        truecolor)       COLOR_DEPTH=3 ;;
        *)
            if printf '%s' "${COLORTERM:-}" | grep -qE 'truecolor|24bit'; then
                COLOR_DEPTH=3
            elif printf '%s' "${TERM:-}" | grep -q '256color'; then
                COLOR_DEPTH=2
            else
                COLOR_DEPTH=1
            fi
            ;;
    esac
else
    COLOR_DEPTH=0
fi

# Named SGR constants: real ESC bytes when color ON, empty strings when OFF so
# `printf '%s'` emits exactly the original bytes. Stored as $'...' literals.
if [ "$COLOR_DEPTH" -gt 0 ]; then
    C_RESET=$'\033[0m'
    C_DIM=$'\033[2m'
    C_GREEN=$'\033[32m'
    C_RED=$'\033[31m'
    C_YELLOW=$'\033[0;93m'
    C_WHITE_BOLD=$'\033[1;37m'
else
    C_RESET=''
    C_DIM=''
    C_GREEN=''
    C_RED=''
    C_YELLOW=''
    C_WHITE_BOLD=''
fi

# Semantic output helpers -----------------------
# Each wraps a WHOLE phrase in color; never inserts an escape inside a phrase.
# All emit on stdout (matching the pre-color streams) unless redirected by caller.
heading() { printf '\n%s▸ %s%s\n' "$C_WHITE_BOLD" "$1" "$C_RESET"; }
ok()      { printf '%s%s%s\n'      "$C_GREEN"      "$1" "$C_RESET"; }
fail()    { printf '%s%s%s\n'      "$C_RED"        "$1" "$C_RESET"; }
step()    { printf '%s%s%s\n'      "$C_DIM"        "$1" "$C_RESET"; }

# run_claude_green CMD... — run a claude plugin command, streaming its stdout so
# only its SUCCESS lines (those carrying a ✔) render green; progress/info lines
# pass through untouched. No duplicate line of our own. When color is off it is a
# pure passthrough, so output is byte-identical to the command's. The pipeline's
# reported status is that of CMD (PIPESTATUS[0]), never the filter, so callers
# still see failures.
run_claude_green() {
    if [ -z "$C_GREEN" ]; then
        "$@"
        return $?
    fi
    "$@" | while IFS= read -r _line; do
        case "$_line" in
            *✔*) printf '%s%s%s\n' "$C_GREEN" "$_line" "$C_RESET" ;;
            *)   printf '%s\n' "$_line" ;;
        esac
    done
    return "${PIPESTATUS[0]}"
}

# Width + wrap ----------------------------------
# term_width — terminal column count: $COLUMNS if set+numeric, else the columns
# field from `stty size </dev/tty`, else 80. Degrades gracefully when stty or
# the tty are unavailable (curated-PATH / non-tty contexts).
term_width() {
    local cols="${COLUMNS:-}"
    if [ -n "$cols" ] && case "$cols" in *[!0-9]*) false ;; *) true ;; esac; then
        printf '%s\n' "$cols"; return 0
    fi
    local size
    size=$( { stty size < /dev/tty; } 2>/dev/null ) || size=''
    if [ -n "$size" ]; then
        cols=${size#* }            # "rows cols" → cols
        case "$cols" in
            ''|*[!0-9]*) ;;        # not numeric → fall through
            *) printf '%s\n' "$cols"; return 0 ;;
        esac
    fi
    printf '80\n'
}

# wrap TEXT [INDENT] — word-wrap TEXT to term_width using a pure-bash word loop
# (no awk). INDENT (default '') is prepended to every output line and counts
# toward the width. A single over-long word is emitted on its own line rather
# than truncated.
wrap() {
    local text="$1" indent="${2:-}"
    local width; width=$(term_width)
    local avail=$(( width - ${#indent} ))
    [ "$avail" -lt 1 ] && avail=1
    local line='' word
    for word in $text; do
        if [ -z "$line" ]; then
            line="$word"
        elif [ "$(( ${#line} + 1 + ${#word} ))" -le "$avail" ]; then
            line="$line $word"
        else
            printf '%s%s\n' "$indent" "$line"
            line="$word"
        fi
    done
    [ -n "$line" ] && printf '%s%s\n' "$indent" "$line"
}

# Reopen stdin from the terminal exactly once, in the interactive branches only.
# Under `curl | bash`, bash has already consumed the whole script body from the
# pipe before main() runs, so fd 0 is an exhausted pipe; reattaching it to the
# terminal is safe and lets `read` (and the embedded selector's fallback) work.
# No re-download, no re-exec, no subshell. The flag makes this idempotent.
_TTY_REATTACHED=0
reattach_tty() {
    [ "$INTERACTIVE" = "1" ] || return 0
    [ "$_TTY_REATTACHED" = "1" ] && return 0
    exec < /dev/tty
    _TTY_REATTACHED=1
}

# Embedded logo ---------------------------------
# print_logo — prints the 8-line, 42-col "YAS!" logo, selected by COLOR_DEPTH.
# Three depth-keyed heredocs are the SINGLE SOURCE OF TRUTH: depth 3 → truecolor
# gradient, depth 2 → alternate gradient, else → the plain block art. The plain
# variant is the alignment source of truth (8 lines, 42 cols). The dev authoring
# files (yas.dos_rebel.{tc,256,plain}.txt) are git-untracked and NOT shipped in
# $PLUGIN_ROOT, so we NEVER read them at runtime — the bytes are embedded below.
# The glyph bytes (U+2588 █ full block, U+2591 ░ light shade) and the ESC
# color bytes are copied verbatim; single-quoted heredoc tags keep them literal.
print_logo() {
    printf '\n'
    case "$COLOR_DEPTH" in
        3)
        cat <<'YAS_TC'
[38;2;29;246;108m [39m[38;2;34;248;100m█[39m[38;2;39;251;93m█[39m[38;2;44;252;86m█[39m[38;2;50;253;79m█[39m[38;2;57;254;72m█[39m[38;2;63;254;65m [39m[38;2;70;254;58m█[39m[38;2;77;254;52m█[39m[38;2;84;253;46m█[39m[38;2;91;251;41m█[39m[38;2;98;249;35m█[39m[38;2;106;247;30m [39m[38;2;113;244;25m [39m[38;2;121;241;21m [39m[38;2;128;237;17m█[39m[38;2;136;233;13m█[39m[38;2;144;229;10m█[39m[38;2;151;224;8m█[39m[38;2;159;219;5m█[39m[38;2;166;213;3m█[39m[38;2;173;207;2m█[39m[38;2;180;201;1m█[39m[38;2;187;195;1m█[39m[38;2;194;188;1m [39m[38;2;200;182;1m [39m[38;2;206;175;2m [39m[38;2;212;167;3m [39m[38;2;217;160;5m█[39m[38;2;223;153;7m█[39m[38;2;228;145;10m█[39m[38;2;232;138;13m█[39m[38;2;236;130;16m█[39m[38;2;240;122;20m█[39m[38;2;243;115;24m█[39m[38;2;246;107;29m█[39m[38;2;249;100;34m█[39m[38;2;251;92;39m [39m[38;2;252;85;45m [39m[38;2;254;78;51m█[39m[38;2;254;71;57m█[39m[38;2;254;64;64m█[39m[38;2;254;58;70m[39m
[38;2;50;253;79m░[39m[38;2;57;254;72m░[39m[38;2;63;254;65m█[39m[38;2;70;254;58m█[39m[38;2;77;254;52m█[39m[38;2;84;253;46m [39m[38;2;91;251;41m░[39m[38;2;98;249;35m░[39m[38;2;106;247;30m█[39m[38;2;113;244;25m█[39m[38;2;121;241;21m█[39m[38;2;128;237;17m [39m[38;2;136;233;13m [39m[38;2;144;229;10m [39m[38;2;151;224;8m█[39m[38;2;159;219;5m█[39m[38;2;166;213;3m█[39m[38;2;173;207;2m░[39m[38;2;180;201;1m░[39m[38;2;187;195;1m░[39m[38;2;194;188;1m░[39m[38;2;200;182;1m░[39m[38;2;206;175;2m█[39m[38;2;212;167;3m█[39m[38;2;217;160;5m█[39m[38;2;223;153;7m [39m[38;2;228;145;10m [39m[38;2;232;138;13m█[39m[38;2;236;130;16m█[39m[38;2;240;122;20m█[39m[38;2;243;115;24m░[39m[38;2;246;107;29m░[39m[38;2;249;100;34m░[39m[38;2;251;92;39m░[39m[38;2;252;85;45m░[39m[38;2;254;78;51m█[39m[38;2;254;71;57m█[39m[38;2;254;64;64m█[39m[38;2;254;58;70m░[39m[38;2;254;52;77m█[39m[38;2;253;46;84m█[39m[38;2;251;40;92m█[39m[38;2;249;35;99m[39m
[38;2;77;254;52m [39m[38;2;84;253;46m░[39m[38;2;91;251;41m░[39m[38;2;98;249;35m█[39m[38;2;106;247;30m█[39m[38;2;113;244;25m█[39m[38;2;121;241;21m [39m[38;2;128;237;17m█[39m[38;2;136;233;13m█[39m[38;2;144;229;10m█[39m[38;2;151;224;8m [39m[38;2;159;219;5m [39m[38;2;166;213;3m [39m[38;2;173;207;2m░[39m[38;2;180;201;1m█[39m[38;2;187;195;1m█[39m[38;2;194;188;1m█[39m[38;2;200;182;1m [39m[38;2;206;175;2m [39m[38;2;212;167;3m [39m[38;2;217;160;5m [39m[38;2;223;153;7m░[39m[38;2;228;145;10m█[39m[38;2;232;138;13m█[39m[38;2;236;130;16m█[39m[38;2;240;122;20m [39m[38;2;243;115;24m░[39m[38;2;246;107;29m█[39m[38;2;249;100;34m█[39m[38;2;251;92;39m█[39m[38;2;252;85;45m [39m[38;2;254;78;51m [39m[38;2;254;71;57m [39m[38;2;254;64;64m [39m[38;2;254;58;70m░[39m[38;2;254;52;77m░[39m[38;2;253;46;84m░[39m[38;2;251;40;92m [39m[38;2;249;35;99m░[39m[38;2;247;30;106m█[39m[38;2;244;25;114m█[39m[38;2;240;21;122m█[39m[38;2;237;17;129m[39m
[38;2;106;247;30m [39m[38;2;113;244;25m [39m[38;2;121;241;21m░[39m[38;2;128;237;17m░[39m[38;2;136;233;13m█[39m[38;2;144;229;10m█[39m[38;2;151;224;8m█[39m[38;2;159;219;5m█[39m[38;2;166;213;3m█[39m[38;2;173;207;2m [39m[38;2;180;201;1m [39m[38;2;187;195;1m [39m[38;2;194;188;1m [39m[38;2;200;182;1m░[39m[38;2;206;175;2m█[39m[38;2;212;167;3m█[39m[38;2;217;160;5m█[39m[38;2;223;153;7m█[39m[38;2;228;145;10m█[39m[38;2;232;138;13m█[39m[38;2;236;130;16m█[39m[38;2;240;122;20m█[39m[38;2;243;115;24m█[39m[38;2;246;107;29m█[39m[38;2;249;100;34m█[39m[38;2;251;92;39m [39m[38;2;252;85;45m░[39m[38;2;254;78;51m░[39m[38;2;254;71;57m█[39m[38;2;254;64;64m█[39m[38;2;254;58;70m█[39m[38;2;254;52;77m█[39m[38;2;253;46;84m█[39m[38;2;251;40;92m█[39m[38;2;249;35;99m█[39m[38;2;247;30;106m█[39m[38;2;244;25;114m█[39m[38;2;240;21;122m [39m[38;2;237;17;129m░[39m[38;2;233;13;137m█[39m[38;2;228;10;144m█[39m[38;2;223;7;152m█[39m[38;2;218;5;159m[39m
[38;2;136;233;13m [39m[38;2;144;229;10m [39m[38;2;151;224;8m [39m[38;2;159;219;5m░[39m[38;2;166;213;3m░[39m[38;2;173;207;2m█[39m[38;2;180;201;1m█[39m[38;2;187;195;1m█[39m[38;2;194;188;1m [39m[38;2;200;182;1m [39m[38;2;206;175;2m [39m[38;2;212;167;3m [39m[38;2;217;160;5m [39m[38;2;223;153;7m░[39m[38;2;228;145;10m█[39m[38;2;232;138;13m█[39m[38;2;236;130;16m█[39m[38;2;240;122;20m░[39m[38;2;243;115;24m░[39m[38;2;246;107;29m░[39m[38;2;249;100;34m░[39m[38;2;251;92;39m░[39m[38;2;252;85;45m█[39m[38;2;254;78;51m█[39m[38;2;254;71;57m█[39m[38;2;254;64;64m [39m[38;2;254;58;70m [39m[38;2;254;52;77m░[39m[38;2;253;46;84m░[39m[38;2;251;40;92m░[39m[38;2;249;35;99m░[39m[38;2;247;30;106m░[39m[38;2;244;25;114m░[39m[38;2;240;21;122m░[39m[38;2;237;17;129m░[39m[38;2;233;13;137m█[39m[38;2;228;10;144m█[39m[38;2;223;7;152m█[39m[38;2;218;5;159m░[39m[38;2;213;3;167m█[39m[38;2;207;2;174m█[39m[38;2;201;1;181m█[39m[38;2;194;1;188m[39m
[38;2;166;213;3m [39m[38;2;173;207;2m [39m[38;2;180;201;1m [39m[38;2;187;195;1m [39m[38;2;194;188;1m░[39m[38;2;200;182;1m█[39m[38;2;206;175;2m█[39m[38;2;212;167;3m█[39m[38;2;217;160;5m [39m[38;2;223;153;7m [39m[38;2;228;145;10m [39m[38;2;232;138;13m [39m[38;2;236;130;16m [39m[38;2;240;122;20m░[39m[38;2;243;115;24m█[39m[38;2;246;107;29m█[39m[38;2;249;100;34m█[39m[38;2;251;92;39m [39m[38;2;252;85;45m [39m[38;2;254;78;51m [39m[38;2;254;71;57m [39m[38;2;254;64;64m░[39m[38;2;254;58;70m█[39m[38;2;254;52;77m█[39m[38;2;253;46;84m█[39m[38;2;251;40;92m [39m[38;2;249;35;99m [39m[38;2;247;30;106m█[39m[38;2;244;25;114m█[39m[38;2;240;21;122m█[39m[38;2;237;17;129m [39m[38;2;233;13;137m [39m[38;2;228;10;144m [39m[38;2;223;7;152m [39m[38;2;218;5;159m░[39m[38;2;213;3;167m█[39m[38;2;207;2;174m█[39m[38;2;201;1;181m█[39m[38;2;194;1;188m░[39m[38;2;188;1;194m░[39m[38;2;181;1;201m░[39m[38;2;174;2;207m [39m[38;2;167;3;212m[39m
[38;2;194;188;1m [39m[38;2;200;182;1m [39m[38;2;206;175;2m [39m[38;2;212;167;3m [39m[38;2;217;160;5m█[39m[38;2;223;153;7m█[39m[38;2;228;145;10m█[39m[38;2;232;138;13m█[39m[38;2;236;130;16m█[39m[38;2;240;122;20m [39m[38;2;243;115;24m [39m[38;2;246;107;29m [39m[38;2;249;100;34m [39m[38;2;251;92;39m█[39m[38;2;252;85;45m█[39m[38;2;254;78;51m█[39m[38;2;254;71;57m█[39m[38;2;254;64;64m█[39m[38;2;254;58;70m [39m[38;2;254;52;77m [39m[38;2;253;46;84m [39m[38;2;251;40;92m█[39m[38;2;249;35;99m█[39m[38;2;247;30;106m█[39m[38;2;244;25;114m█[39m[38;2;240;21;122m█[39m[38;2;237;17;129m░[39m[38;2;233;13;137m░[39m[38;2;228;10;144m█[39m[38;2;223;7;152m█[39m[38;2;218;5;159m█[39m[38;2;213;3;167m█[39m[38;2;207;2;174m█[39m[38;2;201;1;181m█[39m[38;2;194;1;188m█[39m[38;2;188;1;194m█[39m[38;2;181;1;201m█[39m[38;2;174;2;207m [39m[38;2;167;3;212m [39m[38;2;159;5;218m█[39m[38;2;152;7;223m█[39m[38;2;145;10;228m█[39m[38;2;137;13;232m[39m
[38;2;217;160;5m [39m[38;2;223;153;7m [39m[38;2;228;145;10m [39m[38;2;232;138;13m░[39m[38;2;236;130;16m░[39m[38;2;240;122;20m░[39m[38;2;243;115;24m░[39m[38;2;246;107;29m░[39m[38;2;249;100;34m [39m[38;2;251;92;39m [39m[38;2;252;85;45m [39m[38;2;254;78;51m [39m[38;2;254;71;57m░[39m[38;2;254;64;64m░[39m[38;2;254;58;70m░[39m[38;2;254;52;77m░[39m[38;2;253;46;84m░[39m[38;2;251;40;92m [39m[38;2;249;35;99m [39m[38;2;247;30;106m [39m[38;2;244;25;114m░[39m[38;2;240;21;122m░[39m[38;2;237;17;129m░[39m[38;2;233;13;137m░[39m[38;2;228;10;144m░[39m[38;2;223;7;152m [39m[38;2;218;5;159m [39m[38;2;213;3;167m░[39m[38;2;207;2;174m░[39m[38;2;201;1;181m░[39m[38;2;194;1;188m░[39m[38;2;188;1;194m░[39m[38;2;181;1;201m░[39m[38;2;174;2;207m░[39m[38;2;167;3;212m░[39m[38;2;159;5;218m░[39m[38;2;152;7;223m [39m[38;2;145;10;228m [39m[38;2;137;13;232m░[39m[38;2;129;17;237m░[39m[38;2;122;21;240m░[39m[38;2;114;25;244m [39m[38;2;107;29;246m[39m
YAS_TC
            ;;
        2)
        cat <<'YAS_256'
[38;2;106;247;30m [39m[38;2;113;244;25m█[39m[38;2;121;241;21m█[39m[38;2;128;237;17m█[39m[38;2;136;233;13m█[39m[38;2;144;229;10m█[39m[38;2;151;224;8m [39m[38;2;159;219;5m█[39m[38;2;166;213;3m█[39m[38;2;173;207;2m█[39m[38;2;180;201;1m█[39m[38;2;187;195;1m█[39m[38;2;194;188;1m [39m[38;2;200;182;1m [39m[38;2;206;175;2m [39m[38;2;212;167;3m█[39m[38;2;217;160;5m█[39m[38;2;223;153;7m█[39m[38;2;228;145;10m█[39m[38;2;232;138;13m█[39m[38;2;236;130;16m█[39m[38;2;240;122;20m█[39m[38;2;243;115;24m█[39m[38;2;246;107;29m█[39m[38;2;249;100;34m [39m[38;2;251;92;39m [39m[38;2;252;85;45m [39m[38;2;254;78;51m [39m[38;2;254;71;57m█[39m[38;2;254;64;64m█[39m[38;2;254;58;70m█[39m[38;2;254;52;77m█[39m[38;2;253;46;84m█[39m[38;2;251;40;92m█[39m[38;2;249;35;99m█[39m[38;2;247;30;106m█[39m[38;2;244;25;114m█[39m[38;2;240;21;122m [39m[38;2;237;17;129m [39m[38;2;233;13;137m█[39m[38;2;228;10;144m█[39m[38;2;223;7;152m█[39m[38;2;218;5;159m[39m
[38;2;136;233;13m░[39m[38;2;144;229;10m░[39m[38;2;151;224;8m█[39m[38;2;159;219;5m█[39m[38;2;166;213;3m█[39m[38;2;173;207;2m [39m[38;2;180;201;1m░[39m[38;2;187;195;1m░[39m[38;2;194;188;1m█[39m[38;2;200;182;1m█[39m[38;2;206;175;2m█[39m[38;2;212;167;3m [39m[38;2;217;160;5m [39m[38;2;223;153;7m [39m[38;2;228;145;10m█[39m[38;2;232;138;13m█[39m[38;2;236;130;16m█[39m[38;2;240;122;20m░[39m[38;2;243;115;24m░[39m[38;2;246;107;29m░[39m[38;2;249;100;34m░[39m[38;2;251;92;39m░[39m[38;2;252;85;45m█[39m[38;2;254;78;51m█[39m[38;2;254;71;57m█[39m[38;2;254;64;64m [39m[38;2;254;58;70m [39m[38;2;254;52;77m█[39m[38;2;253;46;84m█[39m[38;2;251;40;92m█[39m[38;2;249;35;99m░[39m[38;2;247;30;106m░[39m[38;2;244;25;114m░[39m[38;2;240;21;122m░[39m[38;2;237;17;129m░[39m[38;2;233;13;137m█[39m[38;2;228;10;144m█[39m[38;2;223;7;152m█[39m[38;2;218;5;159m░[39m[38;2;213;3;167m█[39m[38;2;207;2;174m█[39m[38;2;201;1;181m█[39m[38;2;194;1;188m[39m
[38;2;166;213;3m [39m[38;2;173;207;2m░[39m[38;2;180;201;1m░[39m[38;2;187;195;1m█[39m[38;2;194;188;1m█[39m[38;2;200;182;1m█[39m[38;2;206;175;2m [39m[38;2;212;167;3m█[39m[38;2;217;160;5m█[39m[38;2;223;153;7m█[39m[38;2;228;145;10m [39m[38;2;232;138;13m [39m[38;2;236;130;16m [39m[38;2;240;122;20m░[39m[38;2;243;115;24m█[39m[38;2;246;107;29m█[39m[38;2;249;100;34m█[39m[38;2;251;92;39m [39m[38;2;252;85;45m [39m[38;2;254;78;51m [39m[38;2;254;71;57m [39m[38;2;254;64;64m░[39m[38;2;254;58;70m█[39m[38;2;254;52;77m█[39m[38;2;253;46;84m█[39m[38;2;251;40;92m [39m[38;2;249;35;99m░[39m[38;2;247;30;106m█[39m[38;2;244;25;114m█[39m[38;2;240;21;122m█[39m[38;2;237;17;129m [39m[38;2;233;13;137m [39m[38;2;228;10;144m [39m[38;2;223;7;152m [39m[38;2;218;5;159m░[39m[38;2;213;3;167m░[39m[38;2;207;2;174m░[39m[38;2;201;1;181m [39m[38;2;194;1;188m░[39m[38;2;188;1;194m█[39m[38;2;181;1;201m█[39m[38;2;174;2;207m█[39m[38;2;167;3;212m[39m
[38;2;194;188;1m [39m[38;2;200;182;1m [39m[38;2;206;175;2m░[39m[38;2;212;167;3m░[39m[38;2;217;160;5m█[39m[38;2;223;153;7m█[39m[38;2;228;145;10m█[39m[38;2;232;138;13m█[39m[38;2;236;130;16m█[39m[38;2;240;122;20m [39m[38;2;243;115;24m [39m[38;2;246;107;29m [39m[38;2;249;100;34m [39m[38;2;251;92;39m░[39m[38;2;252;85;45m█[39m[38;2;254;78;51m█[39m[38;2;254;71;57m█[39m[38;2;254;64;64m█[39m[38;2;254;58;70m█[39m[38;2;254;52;77m█[39m[38;2;253;46;84m█[39m[38;2;251;40;92m█[39m[38;2;249;35;99m█[39m[38;2;247;30;106m█[39m[38;2;244;25;114m█[39m[38;2;240;21;122m [39m[38;2;237;17;129m░[39m[38;2;233;13;137m░[39m[38;2;228;10;144m█[39m[38;2;223;7;152m█[39m[38;2;218;5;159m█[39m[38;2;213;3;167m█[39m[38;2;207;2;174m█[39m[38;2;201;1;181m█[39m[38;2;194;1;188m█[39m[38;2;188;1;194m█[39m[38;2;181;1;201m█[39m[38;2;174;2;207m [39m[38;2;167;3;212m░[39m[38;2;159;5;218m█[39m[38;2;152;7;223m█[39m[38;2;145;10;228m█[39m[38;2;137;13;232m[39m
[38;2;217;160;5m [39m[38;2;223;153;7m [39m[38;2;228;145;10m [39m[38;2;232;138;13m░[39m[38;2;236;130;16m░[39m[38;2;240;122;20m█[39m[38;2;243;115;24m█[39m[38;2;246;107;29m█[39m[38;2;249;100;34m [39m[38;2;251;92;39m [39m[38;2;252;85;45m [39m[38;2;254;78;51m [39m[38;2;254;71;57m [39m[38;2;254;64;64m░[39m[38;2;254;58;70m█[39m[38;2;254;52;77m█[39m[38;2;253;46;84m█[39m[38;2;251;40;92m░[39m[38;2;249;35;99m░[39m[38;2;247;30;106m░[39m[38;2;244;25;114m░[39m[38;2;240;21;122m░[39m[38;2;237;17;129m█[39m[38;2;233;13;137m█[39m[38;2;228;10;144m█[39m[38;2;223;7;152m [39m[38;2;218;5;159m [39m[38;2;213;3;167m░[39m[38;2;207;2;174m░[39m[38;2;201;1;181m░[39m[38;2;194;1;188m░[39m[38;2;188;1;194m░[39m[38;2;181;1;201m░[39m[38;2;174;2;207m░[39m[38;2;167;3;212m░[39m[38;2;159;5;218m█[39m[38;2;152;7;223m█[39m[38;2;145;10;228m█[39m[38;2;137;13;232m░[39m[38;2;129;17;237m█[39m[38;2;122;21;240m█[39m[38;2;114;25;244m█[39m[38;2;107;29;246m[39m
[38;2;236;130;16m [39m[38;2;240;122;20m [39m[38;2;243;115;24m [39m[38;2;246;107;29m [39m[38;2;249;100;34m░[39m[38;2;251;92;39m█[39m[38;2;252;85;45m█[39m[38;2;254;78;51m█[39m[38;2;254;71;57m [39m[38;2;254;64;64m [39m[38;2;254;58;70m [39m[38;2;254;52;77m [39m[38;2;253;46;84m [39m[38;2;251;40;92m░[39m[38;2;249;35;99m█[39m[38;2;247;30;106m█[39m[38;2;244;25;114m█[39m[38;2;240;21;122m [39m[38;2;237;17;129m [39m[38;2;233;13;137m [39m[38;2;228;10;144m [39m[38;2;223;7;152m░[39m[38;2;218;5;159m█[39m[38;2;213;3;167m█[39m[38;2;207;2;174m█[39m[38;2;201;1;181m [39m[38;2;194;1;188m [39m[38;2;188;1;194m█[39m[38;2;181;1;201m█[39m[38;2;174;2;207m█[39m[38;2;167;3;212m [39m[38;2;159;5;218m [39m[38;2;152;7;223m [39m[38;2;145;10;228m [39m[38;2;137;13;232m░[39m[38;2;129;17;237m█[39m[38;2;122;21;240m█[39m[38;2;114;25;244m█[39m[38;2;107;29;246m░[39m[38;2;99;35;249m░[39m[38;2;92;40;251m░[39m[38;2;84;46;252m [39m[38;2;77;52;254m[39m
[38;2;249;100;34m [39m[38;2;251;92;39m [39m[38;2;252;85;45m [39m[38;2;254;78;51m [39m[38;2;254;71;57m█[39m[38;2;254;64;64m█[39m[38;2;254;58;70m█[39m[38;2;254;52;77m█[39m[38;2;253;46;84m█[39m[38;2;251;40;92m [39m[38;2;249;35;99m [39m[38;2;247;30;106m [39m[38;2;244;25;114m [39m[38;2;240;21;122m█[39m[38;2;237;17;129m█[39m[38;2;233;13;137m█[39m[38;2;228;10;144m█[39m[38;2;223;7;152m█[39m[38;2;218;5;159m [39m[38;2;213;3;167m [39m[38;2;207;2;174m [39m[38;2;201;1;181m█[39m[38;2;194;1;188m█[39m[38;2;188;1;194m█[39m[38;2;181;1;201m█[39m[38;2;174;2;207m█[39m[38;2;167;3;212m░[39m[38;2;159;5;218m░[39m[38;2;152;7;223m█[39m[38;2;145;10;228m█[39m[38;2;137;13;232m█[39m[38;2;129;17;237m█[39m[38;2;122;21;240m█[39m[38;2;114;25;244m█[39m[38;2;107;29;246m█[39m[38;2;99;35;249m█[39m[38;2;92;40;251m█[39m[38;2;84;46;252m [39m[38;2;77;52;254m [39m[38;2;70;58;254m█[39m[38;2;64;64;254m█[39m[38;2;57;71;254m█[39m[38;2;51;78;254m[39m
[38;2;254;71;57m [39m[38;2;254;64;64m [39m[38;2;254;58;70m [39m[38;2;254;52;77m░[39m[38;2;253;46;84m░[39m[38;2;251;40;92m░[39m[38;2;249;35;99m░[39m[38;2;247;30;106m░[39m[38;2;244;25;114m [39m[38;2;240;21;122m [39m[38;2;237;17;129m [39m[38;2;233;13;137m [39m[38;2;228;10;144m░[39m[38;2;223;7;152m░[39m[38;2;218;5;159m░[39m[38;2;213;3;167m░[39m[38;2;207;2;174m░[39m[38;2;201;1;181m [39m[38;2;194;1;188m [39m[38;2;188;1;194m [39m[38;2;181;1;201m░[39m[38;2;174;2;207m░[39m[38;2;167;3;212m░[39m[38;2;159;5;218m░[39m[38;2;152;7;223m░[39m[38;2;145;10;228m [39m[38;2;137;13;232m [39m[38;2;129;17;237m░[39m[38;2;122;21;240m░[39m[38;2;114;25;244m░[39m[38;2;107;29;246m░[39m[38;2;99;35;249m░[39m[38;2;92;40;251m░[39m[38;2;84;46;252m░[39m[38;2;77;52;254m░[39m[38;2;70;58;254m░[39m[38;2;64;64;254m [39m[38;2;57;71;254m [39m[38;2;51;78;254m░[39m[38;2;45;85;252m░[39m[38;2;39;92;251m░[39m[38;2;34;100;249m [39m[38;2;29;107;246m[39m
YAS_256
            ;;
        *)
        cat <<'YAS_PLAIN'
 █████ █████   █████████    █████████  ███
░░███ ░░███   ███░░░░░███  ███░░░░░███░███
 ░░███ ███   ░███    ░███ ░███    ░░░ ░███
  ░░█████    ░███████████ ░░█████████ ░███
   ░░███     ░███░░░░░███  ░░░░░░░░███░███
    ░███     ░███    ░███  ███    ░███░░░ 
    █████    █████   █████░░█████████  ███
   ░░░░░    ░░░░░   ░░░░░  ░░░░░░░░░  ░░░ 
YAS_PLAIN
            ;;
    esac
    printf '%b' "$C_RESET"
    printf '\n'
}

# Embedded single-select menu -------------------
#
# Derived from blurayne's select.sh (single-select subset only):
#   https://gist.github.com/blurayne/f63c5a8521c0eeab8e9afd8baa45c65e
#   Author: Markus Geiger <mg@evolution515.net>
#   "Permission to copy and modify is granted under the Creative Commons
#    Attribution 4.0 license" (CC BY 4.0).
#
# This is a minimal, bash-3.2-safe reduction: no associative arrays, no
# ${var,,} lowercasing, no mapfile. It reads keystrokes from /dev/tty (arrow
# up/down + enter), returns the chosen index in UI_WIDGET_RC and the chosen
# value in UI_WIDGET_VALUE (mirroring the upstream UI_WIDGET_RC convention), and
# accepts an optional preview-callback function name as the first argument —
# invoked with the highlighted value on every highlight change (including the
# initial draw) so the caller can render a live sample beneath the menu.
#
# checkbox.sh (multi-select, by a different author) is deliberately NOT embedded;
# multi-select is a non-goal here.

# UI_WIDGET_RC is a documented widget output (mirrors the upstream convention),
# set by ui_select for callers/future use; nothing reads it in-script yet.
# shellcheck disable=SC2034
UI_WIDGET_RC=-1
UI_WIDGET_VALUE=""

# _read_key — read one keypress from /dev/tty, map to: up / down / enter / other.
# Reads the escape-sequence tail non-blockingly so arrow keys resolve in one call.
_read_key() {
    local k rest=''
    IFS= read -rsn1 k < /dev/tty 2>/dev/null || { printf 'enter'; return; }
    if [ "$k" = "" ]; then printf 'enter'; return; fi
    if [ "$k" = $'\x1b' ]; then
        # Escape sequence: pull the tail (e.g. "[A") with a tiny timeout.
        IFS= read -rsn2 -t 0.01 rest < /dev/tty 2>/dev/null
        case "$rest" in
            '[A'|'OA') printf 'up' ;;
            '[B'|'OB') printf 'down' ;;
            *)         printf 'other' ;;
        esac
        return
    fi
    case "$k" in
        k|K) printf 'up' ;;
        j|J) printf 'down' ;;
        *)   printf 'other' ;;
    esac
}

# ui_select [PREVIEW_CB] LABEL ITEM...
#   PREVIEW_CB — optional function name (pass '' for none) called with the
#                highlighted value on each highlight change.
#   LABEL      — heading shown above the menu.
#   ITEM...    — the selectable values.
# Result: UI_WIDGET_RC = chosen 0-based index, UI_WIDGET_VALUE = chosen value.
ui_select() {
    local preview_cb="$1"; shift
    local label="$1"; shift
    local items=("$@")
    local n=${#items[@]}
    local cur=0 i key drawn_lines=0

    UI_WIDGET_RC=-1
    UI_WIDGET_VALUE=""

    printf '%b%s%b\n' "$C_WHITE_BOLD" "$label" "$C_RESET" > /dev/tty

    # Render the menu and (optionally) the live preview as one block, rewinding
    # over EVERYTHING drawn last time — menu rows plus the variable-height
    # preview — so each highlight change redraws in place instead of stacking.
    _render() {
        if [ "$drawn_lines" -gt 0 ]; then
            i=0
            while [ "$i" -lt "$drawn_lines" ]; do printf '\033[1A\033[2K' > /dev/tty; i=$((i + 1)); done
        fi
        local lines=0
        i=0
        while [ "$i" -lt "$n" ]; do
            if [ "$i" -eq "$cur" ]; then
                if [ "$COLOR_DEPTH" -gt 0 ]; then
                    printf '  \033[93m→ %s\033[0m\n' "${items[$i]}" > /dev/tty
                else
                    printf '  → %s\n' "${items[$i]}" > /dev/tty
                fi
            else
                if [ "$COLOR_DEPTH" -gt 0 ]; then
                    printf '    \033[37m%s\033[0m\n' "${items[$i]}" > /dev/tty
                else
                    printf '    %s\n' "${items[$i]}" > /dev/tty
                fi
            fi
            lines=$((lines + 1))
            i=$((i + 1))
        done
        if [ -n "$preview_cb" ]; then
            local preview
            preview=$("$preview_cb" "${items[$cur]}")
            if [ -n "$preview" ]; then
                printf '%s\n' "$preview" > /dev/tty
                lines=$((lines + $(printf '%s\n' "$preview" | wc -l)))
            fi
        fi
        drawn_lines=$lines
    }

    _render
    while true; do
        key=$(_read_key)
        case "$key" in
            up)   if [ "$cur" -gt 0 ]; then cur=$((cur - 1)); _render; fi ;;
            down) if [ "$cur" -lt $((n - 1)) ]; then cur=$((cur + 1)); _render; fi ;;
            enter)
                # shellcheck disable=SC2034  # documented output; see decl above
                UI_WIDGET_RC=$cur
                UI_WIDGET_VALUE="${items[$cur]}"
                return 0
                ;;
        esac
    done
}

# prompt_yes_no QUESTION DEFAULT
#   DEFAULT — "yes" or "no"; selected on an empty Enter.
# Returns 0 for yes, 1 for no. Reads /dev/tty, bash-3.2-safe.
prompt_yes_no() {
    local question="$1" default="$2" ans hint
    if [ "$default" = "yes" ]; then hint="[Y/n]"; else hint="[y/N]"; fi
    while true; do
        printf '%b%s%b %b%s%b ' "$C_YELLOW" "$question" "$C_RESET" "$C_WHITE_BOLD" "$hint" "$C_RESET" > /dev/tty
        IFS= read -r ans < /dev/tty 2>/dev/null || ans=""
        case "$ans" in
            '') [ "$default" = "yes" ] && return 0 || return 1 ;;
            y|Y|yes|YES|Yes) return 0 ;;
            n|N|no|NO|No)    return 1 ;;
            *) printf '  please answer y or n\n' > /dev/tty ;;
        esac
    done
}

# JSON helper -----------------------------------
# json_py OP [ARGS...] — all JSON reads/transforms/validation go through the
# Python interpreter the script already resolves, so the installer needs no
# external JSON tool dependency.
#
# INJECTION SAFETY (hard requirement): the Python heredoc below is SINGLE-QUOTED
# and reads the op selector, file paths, and values exclusively from sys.argv.
# No `$var` is ever interpolated into the Python source — a path or command
# string containing quotes, backslashes, or shell metacharacters arrives as a
# process argument and cannot corrupt the JSON or inject code. Any future edit
# that splices a shell variable into the heredoc body is a defect.
#
# Interpreter: caller-provided $PYTHON_BIN if set, else find_python (the system
# >=3.10 substrate preflight guarantees). The marketplace/plugin reads run
# before do_wire selects a private interpreter, so they fall through to
# find_python; the wiring reads/writes use the already-selected PYTHON_BIN.
json_py() {
    local _py
    _py="${PYTHON_BIN:-}"
    if [ -z "$_py" ]; then
        _py=$(find_python) || return 1
    fi
    "$_py" - "$@" <<'PY'
import json, sys

def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

op = sys.argv[1]

if op == "get-key":
    # get-key FILE KEY   (KEY may be dotted, e.g. statusLine.command)
    data = load(sys.argv[2])
    cur = data
    for part in sys.argv[3].split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            cur = ""
            break
    if cur is None:
        cur = ""
    if isinstance(cur, (dict, list)):
        sys.stdout.write(json.dumps(cur))
    else:
        sys.stdout.write(str(cur))

elif op == "has-key":
    # has-key FILE KEY            top-level key presence
    # has-key FILE PARENT CHILD   nested: PARENT[CHILD] presence
    # has-key FILE PARENT.CHILD   dotted equivalent of the two-arg form
    data = load(sys.argv[2])
    if len(sys.argv) >= 5:
        parent, child = sys.argv[3], sys.argv[4]
    elif "." in sys.argv[3]:
        parent, child = sys.argv[3].split(".", 1)
    else:
        parent, child = None, sys.argv[3]
    if parent is None:
        present = isinstance(data, dict) and child in data
    else:
        node = data.get(parent) if isinstance(data, dict) else None
        present = isinstance(node, dict) and child in node
    sys.stdout.write("true" if present else "false")

elif op == "installpaths":
    # installpaths FILE   installPath of every .plugins entry whose key
    #                     (ascii-lower) contains "yas", one per line
    data = load(sys.argv[2])
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if isinstance(plugins, dict):
        for key, entries in plugins.items():
            if "yas" not in str(key).lower():
                continue
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    ip = entry.get("installPath")
                    if ip is not None:
                        sys.stdout.write(str(ip) + "\n")

elif op == "set-statusline":
    # set-statusline FILE CMD   merge .statusLine, print serialized JSON
    data = load(sys.argv[2])
    if not isinstance(data, dict):
        data = {}
    data["statusLine"] = {
        "async": True,
        "command": sys.argv[3],
        "refreshInterval": 1,
        "type": "command",
        "padding": 1,
    }
    sys.stdout.write(json.dumps(data, indent=2))

elif op == "del-key":
    # del-key FILE KEY   remove top-level KEY, print serialized JSON
    data = load(sys.argv[2])
    if isinstance(data, dict):
        data.pop(sys.argv[3], None)
    sys.stdout.write(json.dumps(data, indent=2))

elif op == "validate":
    # validate FILE   exit 0 iff json.load succeeds
    try:
        with open(sys.argv[2]) as f:
            json.load(f)
    except Exception:
        sys.exit(1)
    sys.exit(0)

else:
    sys.stderr.write("json_py: unknown op: %s\n" % op)
    sys.exit(2)
PY
}

# Private Python provisioning + detection -------
# — reused by preflight and do_wire.
#
# Version policy: the provisioned CPython is resolved as ${YAS_PYTHON:-3.13}.
# The non-interactive / wire-only default is the STABLE 3.13 (we no longer ship a
# Python prerelease without consent). 3.15 (~6-8 ms faster startup, but currently
# a prerelease) is opt-in: interactively via the Python-version prompt, or in any
# mode by exporting YAS_PYTHON=3.15. Switch later with /yas:config.

# Where a plugin-local, uv-managed CPython lives (provisioned by provision_python).
yas_python_dir() {
    printf '%s/.python\n' "$1"  # $1 = PLUGIN_ROOT
}

# Where a bootstrapped, plugin-local uv lives (installed by provision_python when
# uv is absent from PATH).
yas_uv_dir() {
    printf '%s/.uv\n' "$1"  # $1 = PLUGIN_ROOT
}

# provision_python PLUGIN_ROOT [VER]
# Install (idempotently) a private CPython into $PLUGIN_ROOT/.python via uv and
# echo the concrete interpreter binary path. The version is VER if given, else
# ${YAS_PYTHON:-3.13}: the stable 3.13 by default, 3.15 only when opted in (3.15
# is ~6-8 ms faster to start but currently a prerelease; 3.14 is *slower* than
# 3.13, so the system fallback in find_python avoids it).
#
# This keeps the speed win (when 3.15 is chosen) without mutating the user's
# system Python or PATH: the statusline command points straight at this binary
# (never `uv run`, whose per-invocation overhead — the statusline is spawned on
# every prompt — would erase the win).
#
# uv is the guaranteed engine: if it is on PATH we use it; otherwise we bootstrap
# a plugin-local copy into $PLUGIN_ROOT/.uv (no shell-rc / PATH / system mutation)
# and reference it by absolute path. Returns non-zero only if uv cannot be
# obtained or the install/resolve fails (caller then falls back to find_python).
provision_python() {
    local plugin_root="$1"
    local VER="${2:-${YAS_PYTHON:-3.13}}"

    local pydir uvdir
    pydir=$(yas_python_dir "$plugin_root")
    uvdir=$(yas_uv_dir "$plugin_root")

    # Resolve the uv engine: prefer one already on PATH, else bootstrap.
    local UV_BIN=""
    if command -v uv > /dev/null 2>&1; then
        UV_BIN=$(command -v uv)
    elif [ "$DRY_RUN" = "1" ]; then
        # No network in dry-run: report what we'd bootstrap and continue the
        # synthetic preview below.
        printf "  Would bootstrap uv → %s\n" "$uvdir" 1>&2
    else
        # Bootstrap uv plugin-locally. INSTALLER_NO_MODIFY_PATH keeps it from
        # touching shell rc / PATH; UV_INSTALL_DIR pins the destination. The
        # official installer lands the binary flat at $uvdir/uv (no bin/ nesting).
        printf "  Bootstrapping uv → %s (no system/PATH mutation)\n" "$uvdir" 1>&2
        INSTALLER_NO_MODIFY_PATH=1 UV_INSTALL_DIR="$uvdir" \
            sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' > /dev/null 2>&1 || return 1
        UV_BIN="$uvdir/uv"
        if [ ! -x "$UV_BIN" ]; then
            # Defensive: if a future installer nests the binary, glob for it.
            UV_BIN=$(find "$uvdir" -name uv -type f -perm -u+x 2>/dev/null | head -1)
        fi
        [ -n "$UV_BIN" ] && [ -x "$UV_BIN" ] || return 1
    fi

    if [ "$DRY_RUN" = "1" ]; then
        printf "  Would provision private CPython %s → %s (via uv)\n" "$VER" "$pydir" 1>&2
        # Don't download in dry-run; report a synthetic path so wiring can preview.
        printf '%s/<cpython-%s>/bin/python%s\n' "$pydir" "$VER" "$VER"
        return 0
    fi

    # Install is idempotent: uv reuses an existing $VER in the install dir and,
    # across plugin reinstalls, hydrates from uv's shared download cache (fast).
    UV_PYTHON_INSTALL_DIR="$pydir" "$UV_BIN" python install "$VER" > /dev/null 2>&1 || return 1

    # Resolve the concrete binary. Primary: ask uv, scoped to our managed dir.
    local bin
    bin=$(UV_PYTHON_INSTALL_DIR="$pydir" "$UV_BIN" python find "$VER" --managed-python 2>/dev/null)
    if [ -z "$bin" ] || [ ! -x "$bin" ]; then
        # Fallback: glob the install dir for the newest $VER interpreter.
        # find (not ls) so odd chars in the path are handled; sort -Vr → newest.
        bin=$(find "$pydir" -maxdepth 3 -name "python$VER" -path "*/cpython-$VER*/bin/*" 2>/dev/null | sort -Vr | head -1)
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
    heading "Preflight"
    for tool in claude curl; do
        if command -v "$tool" > /dev/null 2>&1; then
            ok "✔ $tool found"
            continue
        fi
        case "$tool" in
            claude) fail "! claude not found — install from https://claude.ai/download and re-run" ;;
            curl)   fail "! curl not found — install from https://curl.se and re-run" ;;
        esac
        exit 1
    done
    local _py _pyver
    if _py=$(find_python); then
        _pyver=$("$_py" --version 2>&1)
        ok "✔ ${_pyver:-Python 3.10+} found ($_py)"
    else
        fail "! Python 3.10+ not found — install Python 3.10+ and re-run"; exit 1
    fi
    ok "✔ All prerequisites satisfied"
}

preflight_wire_only() {
    heading "Preflight"
    local _py _pyver
    if _py=$(find_python); then
        _pyver=$("$_py" --version 2>&1)
        ok "✔ ${_pyver:-Python 3.10+} found ($_py)"
    else
        fail "! Python 3.10+ not found — install Python 3.10+ and re-run"; exit 1
    fi
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
    heading "Marketplace"
    local present
    present=$(json_py has-key "$CLAUDE_CONFIG_DIR/plugins/known_marketplaces.json" yet-another-statusline 2>/dev/null) || present="false"

    if [ "$present" = "true" ]; then
        if [ "$DRY_RUN" = "1" ]; then
            step "  Would update marketplace: yet-another-statusline"
        else
            step "  Updating marketplace…"
            run_claude_green claude plugin marketplace update yet-another-statusline
        fi
        return
    fi

    if [ "$DRY_RUN" = "1" ]; then
        step "  Would add marketplace: tmck-code/yet-another-statusline"
    else
        step "  Adding marketplace…"
        run_claude_green claude plugin marketplace add tmck-code/yet-another-statusline
    fi
}

# ensure_plugin (full mode only) ----------------
ensure_plugin() {
    heading "Plugin"
    local present
    present=$(json_py has-key "$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json" plugins yas@yet-another-statusline 2>/dev/null) || present="false"

    if [ "$present" = "false" ]; then
        if [ "$DRY_RUN" = "1" ]; then
            step "  Would install: yas@yet-another-statusline"
        else
            step "  Installing yas plugin…"
            run_claude_green claude plugin install yas@yet-another-statusline --scope user
        fi
    else
        if [ "$DRY_RUN" = "1" ]; then
            step "  Would update: yas@yet-another-statusline"
        else
            step "  Updating yas plugin…"
            run_claude_green claude plugin update yas@yet-another-statusline --scope user
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

    heading "Wiring"

    # Renderer discovery
    if [ "$MODE" = "wire-only" ]; then
        PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
        if [ -z "$PLUGIN_ROOT" ]; then
            fail "! CLAUDE_PLUGIN_ROOT is not set — cannot determine plugin root in wire-only mode"
            exit 1
        fi
        if [ ! -f "$PLUGIN_ROOT/claude/statusline_command.py" ]; then
            printf '%b! statusline_command.py not found under CLAUDE_PLUGIN_ROOT: %s%b\n' "$C_RED" "$PLUGIN_ROOT" "$C_RESET"
            exit 1
        fi
    else
        # Full mode: prefer installed_plugins.json, fall back to cache scan

        # From installed_plugins.json
        PLUGIN_ROOT=$(json_py installpaths "$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json" 2>/dev/null \
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
            fail "! yas plugin not found — install first:"
            printf "    claude plugin marketplace add tmck-code/yet-another-statusline\n"
            printf "    claude plugin install yas@yet-another-statusline\n"
            exit 1
        fi
    fi

    SCRIPT="$PLUGIN_ROOT/claude/statusline_command.py"
    printf '%b  Plugin root: %s%b\n' "$C_DIM" "$PLUGIN_ROOT" "$C_RESET"

    # Legacy cleanup
    for f in "$CLAUDE_CONFIG_DIR"/statusline-info-*; do
        [ -e "$f" ] || continue
        rm -f "$f" && printf '%b  Removed legacy %s%b\n' "$C_DIM" "$(basename "$f")" "$C_RESET"
    done

    # Python selection: prefer a private, plugin-local CPython provisioned via uv
    # (fastest startup, no system mutation), at the resolved version (3.13 default,
    # 3.15 opt-in). Fall back to a system interpreter (>=3.10, avoiding 3.14) when
    # uv is unavailable. PY_VER is set by the Python-version prompt / YAS_PYTHON.
    heading "Python"
    local VER="${PY_VER:-${YAS_PYTHON:-3.13}}"
    if PYTHON_BIN=$(provision_python "$PLUGIN_ROOT" "$VER"); then
        printf '%b  Python: %s (private uv-managed %s)%b\n' "$C_DIM" "$PYTHON_BIN" "$VER" "$C_RESET"
    elif PYTHON_BIN=$(find_python); then
        printf '%b  Python: %s (system fallback)%b\n' "$C_DIM" "$PYTHON_BIN" "$C_RESET"
    else
        fail "! Python 3.10+ not found — install Python 3.10+ (or uv) and re-run"; exit 1
    fi

    # Interactive config wizard: runs AFTER provisioning (previews need the
    # interpreter + shipped assets) and BEFORE the settings write. Guarded behind
    # INTERACTIVE + RUN_WIZARD so non-interactive / wire-only paths write no
    # yas.toml. PLUGIN_ROOT and PYTHON_BIN are visible here for render_preview.
    if [ "$INTERACTIVE" = "1" ] && [ "${RUN_WIZARD:-0}" = "1" ] && [ "$DRY_RUN" != "1" ]; then
        run_wizard
    fi

    # Exact-match skip
    local NEW_CMD OLD_CMD
    NEW_CMD="\"$PYTHON_BIN\" \"$SCRIPT\""
    OLD_CMD=$(json_py get-key "$SETTINGS" statusLine.command 2>/dev/null || printf '')
    if [ "$OLD_CMD" = "$NEW_CMD" ]; then
        ok "  statusLine already set to current version — skipping."
        printf '%b  Config dir: %s%b\n' "$C_DIM" "$CLAUDE_CONFIG_DIR" "$C_RESET"
        ok "  Done. Reload Claude Code to activate the statusline."
        return 0
    fi

    # dry-run wiring
    if [ "$DRY_RUN" = "1" ]; then
        printf '%b  Would wire statusLine.command → %s%b\n' "$C_DIM" "$NEW_CMD" "$C_RESET"
        exit 0
    fi

    # Atomic write with backup / validate / restore
    local BAK=""
    if [ ! -f "$SETTINGS" ]; then
        printf '{}\n' > "$SETTINGS"
        printf '%b  Created %s%b\n' "$C_DIM" "$SETTINGS" "$C_RESET"
    else
        BAK="${SETTINGS}.bak-yas-$(date -u +%Y%m%dT%H%M%SZ)"
        cp "$SETTINGS" "$BAK"
        printf '%b  Backed up → %s%b\n' "$C_DIM" "$(basename "$BAK")" "$C_RESET"
    fi

    local _result
    if ! _result=$(json_py set-statusline "$SETTINGS" "$NEW_CMD") || [ -z "$_result" ]; then
        fail "! JSON merge failed — settings.json unchanged"; exit 1
    fi

    local _tmp
    _tmp=$(mktemp "${SETTINGS}.XXXXXXXXXX")
    printf '%s\n' "$_result" > "$_tmp" || { rm -f "$_tmp"; fail "! write failed — settings.json unchanged"; exit 1; }
    mv "$_tmp" "$SETTINGS"

    if ! json_py validate "$SETTINGS" 2>/dev/null; then
        fail "! settings.json invalid after write — restoring backup"
        [ -n "$BAK" ] && cp "$BAK" "$SETTINGS"
        exit 1
    fi

    [ -n "$OLD_CMD" ] && [ "$OLD_CMD" != "$NEW_CMD" ] && printf '%b  Replaced stale path: %s%b\n' "$C_DIM" "$OLD_CMD" "$C_RESET"
    printf '%b  statusLine set → %s%b\n' "$C_GREEN" "$NEW_CMD" "$C_RESET"
    printf '%b  Config dir: %s%b\n' "$C_DIM" "$CLAUDE_CONFIG_DIR" "$C_RESET"
    ok "  Done. Reload Claude Code to activate the statusline."
}

# do_uninstall ---------------------------------
# — remove statusLine from settings.json (atomic, with backup/validate/restore)
# - clean up legacy statusline-info-* files
# - with --full, also uninstall the plugin via `claude plugin uninstall`
do_uninstall() {
    local SETTINGS="$CLAUDE_CONFIG_DIR/settings.json"

    heading "Settings"

    # Legacy cleanup (always, even if settings has nothing to remove)
    for f in "$CLAUDE_CONFIG_DIR"/statusline-info-*; do
        [ -e "$f" ] || continue
        if [ "$DRY_RUN" = "1" ]; then
            printf '%b  Would remove legacy %s%b\n' "$C_DIM" "$(basename "$f")" "$C_RESET"
        else
            rm -f "$f" && printf '%b  Removed legacy %s%b\n' "$C_DIM" "$(basename "$f")" "$C_RESET"
        fi
    done

    # Remove statusLine key from settings.json
    if [ ! -f "$SETTINGS" ]; then
        step "  settings.json not found — nothing to unwire."
    else
        local HAS_KEY
        HAS_KEY=$(json_py has-key "$SETTINGS" statusLine 2>/dev/null) || HAS_KEY="false"
        if [ "$HAS_KEY" != "true" ]; then
            step "  statusLine not present in settings.json — nothing to unwire."
        elif [ "$DRY_RUN" = "1" ]; then
            printf '%b  Would remove statusLine from %s%b\n' "$C_DIM" "$SETTINGS" "$C_RESET"
        else
            local BAK
            BAK="${SETTINGS}.bak-yas-$(date -u +%Y%m%dT%H%M%SZ)"
            cp "$SETTINGS" "$BAK"
            printf '%b  Backed up → %s%b\n' "$C_DIM" "$(basename "$BAK")" "$C_RESET"

            local _result
            if ! _result=$(json_py del-key "$SETTINGS" statusLine) || [ -z "$_result" ]; then
                fail "! JSON edit failed — settings.json unchanged"; exit 1
            fi

            local _tmp
            _tmp=$(mktemp "${SETTINGS}.XXXXXXXXXX")
            printf '%s\n' "$_result" > "$_tmp" || { rm -f "$_tmp"; fail "! write failed — settings.json unchanged"; exit 1; }
            mv "$_tmp" "$SETTINGS"

            if ! json_py validate "$SETTINGS" 2>/dev/null; then
                fail "! settings.json invalid after write — restoring backup"
                cp "$BAK" "$SETTINGS"
                exit 1
            fi
            ok "  Removed statusLine from settings.json"
        fi
    fi

    # Private uv-managed CPython cleanup (best-effort).
    # Discover the plugin root the same ways do_wire does, then remove its
    # .python dir if present.
    local UN_ROOT=""
    if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && { [ -d "$(yas_python_dir "$CLAUDE_PLUGIN_ROOT")" ] || [ -d "$(yas_uv_dir "$CLAUDE_PLUGIN_ROOT")" ]; }; then
        UN_ROOT="$CLAUDE_PLUGIN_ROOT"
    else
        UN_ROOT=$(json_py installpaths "$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json" 2>/dev/null \
            | while IFS= read -r d; do
                { [ -d "$(yas_python_dir "$d")" ] || [ -d "$(yas_uv_dir "$d")" ]; } && echo "$d"
              done \
            | head -1)
    fi
    if [ -n "$UN_ROOT" ]; then
        heading "Runtime"
        local PYDIR
        PYDIR=$(yas_python_dir "$UN_ROOT")
        if [ -d "$PYDIR" ]; then
            if [ "$DRY_RUN" = "1" ]; then
                printf '%b  Would remove private CPython dir %s%b\n' "$C_DIM" "$PYDIR" "$C_RESET"
            else
                rm -rf "$PYDIR" && printf '%b  Removed private CPython dir %s%b\n' "$C_GREEN" "$PYDIR" "$C_RESET"
            fi
        fi
        local UVDIR
        UVDIR=$(yas_uv_dir "$UN_ROOT")
        if [ -d "$UVDIR" ]; then
            if [ "$DRY_RUN" = "1" ]; then
                printf '%b  Would remove bootstrapped uv dir %s%b\n' "$C_DIM" "$UVDIR" "$C_RESET"
            else
                rm -rf "$UVDIR" && printf '%b  Removed bootstrapped uv dir %s%b\n' "$C_GREEN" "$UVDIR" "$C_RESET"
            fi
        fi
    fi

    # Plugin uninstall (--full only)
    if [ "$FULL_FLAG" = "1" ]; then
        heading "Plugin"
        command -v claude > /dev/null 2>&1 || { fail "! claude not found — cannot uninstall plugin"; exit 1; }
        local present
        present=$(json_py has-key "$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json" plugins yas@yet-another-statusline 2>/dev/null) || present="false"
        if [ "$present" != "true" ]; then
            step "  yas plugin not installed — skipping plugin uninstall."
        elif [ "$DRY_RUN" = "1" ]; then
            step "  Would uninstall: yas@yet-another-statusline"
        else
            step "  Uninstalling yas plugin…"
            run_claude_green claude plugin uninstall yas@yet-another-statusline --scope user
        fi
    fi

    if [ "$DRY_RUN" != "1" ]; then ok "  Done."; fi
}

# Python-version selection ----------------------
# Sets the global PY_VER consumed by do_wire → provision_python.
#   YAS_PYTHON=3.15 (any mode) forces 3.15 and short-circuits the prompt.
#   Interactive (no YAS_PYTHON) → prompt; yes → 3.15, no → 3.13.
#   Non-interactive (no YAS_PYTHON) → 3.13.
PY_VER=""
resolve_python_version() {
    if [ -n "${YAS_PYTHON:-}" ]; then
        PY_VER="$YAS_PYTHON"
        return 0
    fi
    if [ "$INTERACTIVE" = "1" ]; then
        if prompt_yes_no "Use Python 3.15 (faster, prerelease)?" "no"; then
            PY_VER="3.15"
        else
            PY_VER="3.13"
        fi
    else
        PY_VER="3.13"
    fi
}

# Side-effect-free preview render ---------------
# render_preview GLYPH_MODE THEME — render the shipped sample statusline with the
# highlighted glyph mode + theme beneath the menu, at a fixed COLUMNS. Both the
# renderer and the sample JSON are git-tracked so they exist under $PLUGIN_ROOT.
#
# Side effects: app.main() writes $CLAUDE_DIR/statusline-output/statusline.<id>.json
# (CLAUDE_DIR derives from CLAUDE_CONFIG_DIR). We point CLAUDE_CONFIG_DIR at a
# throwaway mktemp -d for the subprocess ONLY (inline env on the command — never
# exported into the installer env), so any payload write lands in scratch and is
# discarded. The temp dir is removed right after.
render_preview() {
    local gmode="$1" theme="$2"
    local script="$PLUGIN_ROOT/claude/statusline_command.py"
    local sample="$PLUGIN_ROOT/ops/session-info-example.json"
    [ -n "${PYTHON_BIN:-}" ] && [ -f "$script" ] && [ -f "$sample" ] || return 0

    local scratch
    scratch=$(mktemp -d 2>/dev/null) || return 0
    # Emit on stdout (not /dev/tty) so ui_select can capture the output and count
    # its height for the in-place redraw rewind.
    printf '\n'
    CLAUDE_CONFIG_DIR="$scratch" YAS_GLYPH_MODE="$gmode" YAS_THEME="$theme" COLUMNS=100 \
        "$PYTHON_BIN" "$script" < "$sample" 2>/dev/null
    printf '\n'
    rm -rf "$scratch"
}

# Preview callbacks: ui_select invokes these with the highlighted value. The
# other axis is held at its already-chosen value (or its default).
WIZ_GLYPH_MODE="nerdfont"
WIZ_THEME="claude-dark"
_preview_glyph() { render_preview "$1" "$WIZ_THEME"; }
_preview_theme() { render_preview "$WIZ_GLYPH_MODE" "$1"; }

# build_yas_toml GLYPH_MODE LABELS THEME SOFT_LIMIT
# Emit a commented yas.toml template mirroring yas.example.toml's structure with
# the four chosen values interpolated. Does NOT merge an existing file.
build_yas_toml() {
    local glyph_mode="$1" labels="$2" theme="$3" soft_limit="$4"
    cat <<EOF
# yas.toml — yet-another-statusline configuration
#
# Generated by ops/install.sh. Precedence (highest wins): CLI flag → YAS_* env
# var → legacy-alias env var → this file → built-in default. Re-run /yas:config
# to regenerate. See yas.example.toml for every available knob and per-model
# [[tokens.model]] soft_limit overrides.

[layout]
# bool; wide layout only — paint small superscript section labels above each value.
labels = $labels

[tokens]
# int > 0; tokens; context-fill bar / % threshold. Raise for 1M-context models.
# Per-model overrides live under [[tokens.model]] (see yas.example.toml / README).
soft_limit = $soft_limit

[appearance]
# Theme name; one of the keys in claude/yas/themes.py THEMES.
theme = "$theme"

[appearance.glyphs]
# Glyph mode: nerdfont (default) / ascii / unicode / github.
mode = "$glyph_mode"
EOF
}

# Interactive config wizard ---------------------
# Collects the four user-facing options (glyph mode, theme, labels, soft limit)
# with live previews, then writes / prints $CLAUDE_CONFIG_DIR/yas.toml. Guarded
# entirely behind INTERACTIVE by the caller — never runs non-interactively.
run_wizard() {
    local toml_path="$CLAUDE_CONFIG_DIR/yas.toml"

    heading "Configuration" > /dev/tty

    # Existing-file check: keep-as-is vs reconfigure. Keep skips everything.
    if [ -f "$toml_path" ]; then
        printf '\nAn existing yas.toml was found at %s\n' "$toml_path" > /dev/tty
        if prompt_yes_no "Keep it as-is (skip the wizard)?" "yes"; then
            ok "  Keeping existing yas.toml." > /dev/tty
            return 0
        fi
    fi

    # 1. Glyph mode (live preview).
    ui_select _preview_glyph "Glyph mode:" nerdfont ascii unicode github
    WIZ_GLYPH_MODE="$UI_WIDGET_VALUE"

    # 2. Theme (live preview).
    ui_select _preview_theme "Theme:" \
        claude-dark claude-light catppuccin-latte catppuccin-mocha dracula \
        gruvbox-dark gruvbox-light nord one-dark one-light solarized-dark \
        solarized-light tokyo-night palenight
    WIZ_THEME="$UI_WIDGET_VALUE"

    # 3. Labels (yes/no, default on).
    local labels="false"
    if prompt_yes_no "Show section labels?" "yes"; then labels="true"; fi

    # 4. Soft limit (preset menu, no free-form entry). Labels are comma-grouped
    # for readability with "(default)" on the first; the chosen integer is
    # recovered by stripping every non-digit so build_yas_toml gets a bare int.
    ui_select "" "Token soft limit:" \
        "150,000 (default)" "200,000" "500,000" "1,000,000"
    local soft_limit
    soft_limit=$(printf '%s' "$UI_WIDGET_VALUE" | tr -cd '0-9')
    wrap "Tip: per-model [[tokens.model]] limits and advanced config live in the README and yas.example.toml." "  " > /dev/tty

    # Build the file content once.
    local content
    content=$(build_yas_toml "$WIZ_GLYPH_MODE" "$labels" "$WIZ_THEME" "$soft_limit")

    # Overwrite vs print-to-STDOUT.
    if ! prompt_yes_no "Write this configuration to $toml_path?" "yes"; then
        printf '\n# --- yas.toml (copy/paste) ---\n' > /dev/tty
        printf '%s\n' "$content"
        return 0
    fi

    # Atomic write (mktemp + mv), then validate via tomllib where available.
    local tmp
    tmp=$(mktemp "${toml_path}.XXXXXXXXXX") || { fail '! could not create temp file — yas.toml unchanged' > /dev/tty; return 0; }
    printf '%s\n' "$content" > "$tmp" || { rm -f "$tmp"; fail '! write failed — yas.toml unchanged' > /dev/tty; return 0; }

    if [ -n "${PYTHON_BIN:-}" ]; then
        if ! "$PYTHON_BIN" -c 'import tomllib,sys; tomllib.load(open(sys.argv[1],"rb"))' "$tmp" 2>/dev/null; then
            rm -f "$tmp"
            fail '! generated yas.toml failed to parse — leaving existing file untouched' > /dev/tty
            return 0
        fi
    fi

    mv "$tmp" "$toml_path"
    ok "  Wrote $toml_path" > /dev/tty
}

# post_install_message — points users at /yas:config for later reconfiguration.
post_install_message() {
    printf '\n'
    wrap "Reconfigure any time with /yas:config (glyph mode, theme, labels, soft limit, and Python version — including switching to Python 3.15)." "  "
}

main() {
    if [ "$MODE" = "uninstall" ]; then
        do_uninstall
    elif [ "$MODE" = "reconfigure" ]; then
        # Reconfigure has no useful non-interactive behaviour — error out rather
        # than silently doing nothing. It re-runs the logo + Python prompt +
        # wizard + re-wire against the ALREADY-installed plugin, skipping
        # marketplace registration and plugin install/update entirely.
        if [ "$INTERACTIVE" != "1" ]; then
            fail "! --reconfigure requires an interactive terminal (set YAS_NO_TTY unset and run attached to a tty)"
            exit 1
        fi
        reattach_tty
        print_logo
        resolve_python_version
        preflight_wire_only
        RUN_WIZARD=1
        do_wire
        post_install_message
    elif [ "$MODE" = "full" ]; then
        # Interactive full flow: logo + Python prompt fire BEFORE plugin install
        # (they need no shipped asset); the wizard fires inside do_wire AFTER
        # provisioning (previews need the interpreter + shipped assets).
        if [ "$INTERACTIVE" = "1" ]; then
            reattach_tty
            print_logo
            RUN_WIZARD=1
        fi
        resolve_python_version
        preflight_full
        ensure_marketplace
        ensure_plugin
        do_wire
        post_install_message
    else
        if [ "$INTERACTIVE" = "1" ]; then
            reattach_tty
            print_logo
            RUN_WIZARD=1
        fi
        resolve_python_version
        preflight_wire_only
        do_wire
        post_install_message
    fi
}
main
