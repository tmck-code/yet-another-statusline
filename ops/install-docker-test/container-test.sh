#!/usr/bin/env bash
# container-test.sh — runs INSIDE the stock claude-container:python image.
#
# Proves ops/install.sh works end-to-end with NO jq anywhere (the stock image
# ships no jq — the harness's own JSON reads go through a python one-liner too)
# across three scenarios:
#
#   S1 (uv present): install.sh --wire-only provisions a private uv-managed
#       CPython 3.15 under .python, wires it, renders, settings shape is correct.
#   S2 (uv hidden):  with `uv` removed from PATH (a curated /app/pybin holds only
#       python/python3 symlinks; uv lives in /usr/local/bin and /uv/.venv/bin,
#       neither of which is on the scrubbed PATH), command -v uv fails → the
#       script BOOTSTRAPS uv into $CLAUDE_PLUGIN_ROOT/.uv, then provisions 3.15.
#   S3 (uninstall):  install.sh --uninstall strips .statusLine AND removes both
#       $CLAUDE_PLUGIN_ROOT/.python and $CLAUDE_PLUGIN_ROOT/.uv.
#
# NOTE: -e is intentionally omitted. install.sh and several probes below are
# expected to exit non-zero on some branches; -e would abort mid-assertion. We
# capture exit codes explicitly and tally PASS/FAIL ourselves.
set -uo pipefail

REPO=/repo
# /work would live at filesystem root, which the non-root `claude` user can't
# create. /app is writable by claude (and is the workdir), so stage there.
WORK=/app/work

FAILS=0
pass() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; FAILS=$((FAILS + 1)); }

# Resolve a python for the harness's OWN json reads (the image has no jq). The
# image's only system interpreter is /uv/.venv/bin/python (3.14.x). Prefer one on
# PATH, fall back to that known location.
HARNESS_PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
[ -n "$HARNESS_PY" ] || HARNESS_PY=/uv/.venv/bin/python
printf '== Harness python: %s ==\n' "$HARNESS_PY"

# json_get FILE DOTTED_KEY — print a (possibly nested) string value or "".
json_get() {
    "$HARNESS_PY" - "$1" "$2" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except Exception:
    data = {}
cur = data
for part in sys.argv[2].split("."):
    if isinstance(cur, dict) and part in cur:
        cur = cur[part]
    else:
        cur = ""
        break
if cur is None:
    cur = ""
sys.stdout.write(cur if isinstance(cur, str) else json.dumps(cur))
PY
}

# json_shape_ok FILE — print "true" iff .statusLine is an object carrying all of
# async/command/refreshInterval/type/padding.
json_shape_ok() {
    "$HARNESS_PY" - "$1" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except Exception:
    print("false"); sys.exit(0)
sl = data.get("statusLine") if isinstance(data, dict) else None
keys = ("async", "command", "refreshInterval", "type", "padding")
ok = isinstance(sl, dict) and all(k in sl for k in keys)
print("true" if ok else "false")
PY
}

# json_has_statusline FILE — print "true"/"false" for top-level statusLine key.
json_has_statusline() {
    "$HARNESS_PY" - "$1" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except Exception:
    print("false"); sys.exit(0)
print("true" if isinstance(data, dict) and "statusLine" in data else "false")
PY
}

# json_valid FILE — exit 0 iff parseable.
json_valid() {
    "$HARNESS_PY" - "$1" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        json.load(f)
except Exception:
    sys.exit(1)
PY
}

# --- (a) writable copy of the read-only mounted repo --------------------------
printf '== Staging writable repo copy at %s ==\n' "$WORK"
rm -rf "$WORK"
mkdir -p "$WORK"
cp -a "$REPO"/. "$WORK"/
rm -rf "$WORK/.git"  # not needed; skipped for speed

# --- (b) isolated plugin root + config dir ------------------------------------
export CLAUDE_PLUGIN_ROOT="$WORK"
export CLAUDE_CONFIG_DIR="$WORK/.claude-test"
mkdir -p "$CLAUDE_CONFIG_DIR"
SETTINGS="$CLAUDE_CONFIG_DIR/settings.json"
printf '  CLAUDE_PLUGIN_ROOT=%s\n' "$CLAUDE_PLUGIN_ROOT"
printf '  CLAUDE_CONFIG_DIR=%s\n' "$CLAUDE_CONFIG_DIR"

# assert_wired_3_15 — shared S1/S2 assertion: settings wired to a private
# uv-managed CPython 3.15 under .python, renders non-empty, shape correct.
assert_wired_3_15() {
    local scenario="$1"

    printf '\n== %s/A1: wired-to-uv-3.15 ==\n' "$scenario"
    local CMD
    CMD=$(json_get "$SETTINGS" statusLine.command)
    printf '  statusLine.command = %s\n' "$CMD"
    if [ -z "$CMD" ]; then
        fail "$scenario A1: no .statusLine.command in settings.json"
        return
    fi
    local A1_OK=1
    case "$CMD" in
        */.python/*) : ;;
        *) A1_OK=0; printf '  - command does not reference .python/\n' ;;
    esac
    case "$CMD" in
        *python3.15*|*cpython-3.15*) : ;;
        *) A1_OK=0; printf '  - command lacks a python3.15 / cpython-3.15 path component\n' ;;
    esac
    case "$CMD" in
        *python3.14*|*cpython-3.14*) A1_OK=0; printf '  - command points at 3.14\n' ;;
    esac
    local BIN
    BIN=$(printf '%s' "$CMD" | sed -n 's/^"\([^"]*\)".*/\1/p')
    printf '  interpreter binary = %s\n' "$BIN"
    case "$BIN" in
        */python3) A1_OK=0; printf '  - interpreter is a bare system python3\n' ;;
    esac
    if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then
        A1_OK=0; printf '  - interpreter binary missing or not executable\n'
    else
        local VER
        VER=$("$BIN" --version 2>&1)
        printf '  interpreter --version = %s\n' "$VER"
        case "$VER" in
            "Python 3.15"*) : ;;
            *) A1_OK=0; printf '  - interpreter is not Python 3.15\n' ;;
        esac
    fi
    if [ "$A1_OK" -eq 1 ]; then
        pass "$scenario A1: wired to private uv-managed CPython 3.15 ($BIN)"
    else
        fail "$scenario A1: not wired to a private uv-managed CPython 3.15"
    fi

    printf '\n== %s/A2: renders ==\n' "$scenario"
    local EX="$WORK/ops/session-info-example.json"
    local RENDER RENDER_RC USED_PYTHONPATH=0
    RENDER=$(eval "$CMD" < "$EX" 2>&1)
    RENDER_RC=$?
    if [ "$RENDER_RC" -ne 0 ] || [ -z "$RENDER" ]; then
        printf '  bare run failed (rc=%d) — retrying with PYTHONPATH=%s/claude\n' "$RENDER_RC" "$WORK"
        RENDER=$(export PYTHONPATH="$WORK/claude"; eval "$CMD" < "$EX" 2>&1)
        RENDER_RC=$?
        USED_PYTHONPATH=1
    fi
    if [ "$RENDER_RC" -eq 0 ] && [ -n "$RENDER" ]; then
        if [ "$USED_PYTHONPATH" -eq 1 ]; then
            pass "$scenario A2: renders non-empty output (rc=0) — NOTE: required PYTHONPATH=$WORK/claude"
        else
            pass "$scenario A2: renders non-empty output (rc=0) via bare command (no PYTHONPATH needed)"
        fi
        printf '  first render line:\n'; printf '%s\n' "$RENDER" | head -1
    else
        fail "$scenario A2: render failed (rc=$RENDER_RC, empty=$([ -z "$RENDER" ] && echo yes || echo no))"
    fi

    printf '\n== %s/A3: settings shape ==\n' "$scenario"
    if json_valid "$SETTINGS"; then
        if [ "$(json_shape_ok "$SETTINGS")" = "true" ]; then
            pass "$scenario A3: settings.json valid; .statusLine has async/command/refreshInterval/type/padding"
        else
            fail "$scenario A3: .statusLine missing one of async/command/refreshInterval/type/padding"
        fi
    else
        fail "$scenario A3: settings.json is not valid JSON"
    fi
}

# === S1: uv present ===========================================================
printf '\n############ S1: uv present ############\n'
printf '  uv on PATH: %s\n' "$(command -v uv || echo '<none>')"
printf '\n== Running: bash %s/ops/install.sh --wire-only ==\n' "$WORK"
S1_OUT=$(bash "$WORK/ops/install.sh" --wire-only 2>&1)
S1_RC=$?
printf '%s\n' "$S1_OUT"
printf '  install.sh exit code: %d\n' "$S1_RC"
[ "$S1_RC" -eq 0 ] || fail "S1: install.sh --wire-only exited non-zero ($S1_RC)"
assert_wired_3_15 "S1"

# === S2: uv hidden → bootstrap ================================================
# uv exists at /usr/local/bin/uv AND /uv/.venv/bin/uv (the latter co-located with
# the only system python, 3.14.x). Build a curated /app/pybin with python/python3
# symlinks to that interpreter and run with PATH=/app/pybin:/usr/bin:/bin — this
# keeps the python substrate + curl (in /usr/bin) but excludes BOTH uv dirs, so
# `command -v uv` genuinely fails and the bootstrap path runs.
printf '\n############ S2: uv hidden → bootstrap ############\n'
SYS_PY=/uv/.venv/bin/python
[ -x "$SYS_PY" ] || SYS_PY=$(command -v python3 || command -v python)
PYBIN=/app/pybin
rm -rf "$PYBIN"; mkdir -p "$PYBIN"
ln -sf "$SYS_PY" "$PYBIN/python"
ln -sf "$SYS_PY" "$PYBIN/python3"
printf '  curated python substrate: %s → %s\n' "$PYBIN/python" "$SYS_PY"

# Fresh config + plugin root so S2 provisions from scratch (independent of S1).
S2_ROOT=/app/work-s2
rm -rf "$S2_ROOT"; mkdir -p "$S2_ROOT"
cp -a "$WORK"/. "$S2_ROOT"/
export CLAUDE_PLUGIN_ROOT="$S2_ROOT"
export CLAUDE_CONFIG_DIR="$S2_ROOT/.claude-test"
mkdir -p "$CLAUDE_CONFIG_DIR"
SETTINGS="$CLAUDE_CONFIG_DIR/settings.json"

printf '\n== Running with PATH=%s:/usr/bin:/bin (uv hidden) ==\n' "$PYBIN"
S2_OUT=$(PATH="$PYBIN:/usr/bin:/bin" bash "$S2_ROOT/ops/install.sh" --wire-only 2>&1)
S2_RC=$?
printf '%s\n' "$S2_OUT"
printf '  install.sh exit code: %d\n' "$S2_RC"
[ "$S2_RC" -eq 0 ] || fail "S2: install.sh --wire-only (uv hidden) exited non-zero ($S2_RC)"

# Confirm uv was genuinely hidden during the run.
case "$S2_OUT" in
    *"Bootstrapping uv"*) pass "S2: bootstrap path taken (uv was hidden)" ;;
    *) fail "S2: bootstrap message absent — uv may not have been hidden" ;;
esac

# S2/B1: the bootstrapped uv binary exists and is executable under .uv.
printf '\n== S2/B1: bootstrapped uv binary ==\n'
UVBIN="$S2_ROOT/.uv/uv"
if [ -x "$UVBIN" ]; then
    pass "S2 B1: bootstrapped uv present and executable ($UVBIN, $("$UVBIN" --version 2>&1))"
else
    fail "S2 B1: $UVBIN missing or not executable"
fi

assert_wired_3_15 "S2"

# === S3: uninstall removes .statusLine + .python + .uv ========================
printf '\n############ S3: uninstall ############\n'
PYDIR="$S2_ROOT/.python"
UVDIR="$S2_ROOT/.uv"
[ -d "$PYDIR" ] && printf '  pre-uninstall: %s exists\n' "$PYDIR"
[ -d "$UVDIR" ] && printf '  pre-uninstall: %s exists\n' "$UVDIR"
S3_OUT=$(PATH="$PYBIN:/usr/bin:/bin" bash "$S2_ROOT/ops/install.sh" --uninstall 2>&1)
S3_RC=$?
printf '%s\n' "$S3_OUT"
printf '  uninstall exit code: %d\n' "$S3_RC"
S3_OK=1
[ "$S3_RC" -eq 0 ] || { S3_OK=0; printf '  - uninstall exited non-zero\n'; }
if [ "$(json_has_statusline "$SETTINGS")" != "false" ]; then
    S3_OK=0; printf '  - .statusLine still present\n'
fi
if [ -d "$PYDIR" ]; then S3_OK=0; printf '  - %s still exists\n' "$PYDIR"; fi
if [ -d "$UVDIR" ]; then S3_OK=0; printf '  - %s still exists\n' "$UVDIR"; fi
if [ "$S3_OK" -eq 1 ]; then
    pass "S3: uninstall removed .statusLine, $PYDIR and $UVDIR"
else
    fail "S3: uninstall did not fully round-trip"
fi

# --- summary ------------------------------------------------------------------
printf '\n== SUMMARY ==\n'
if [ "$FAILS" -eq 0 ]; then
    printf 'ALL SCENARIOS PASSED (S1, S2, S3)\n'
    exit 0
else
    printf '%d ASSERTION(S) FAILED\n' "$FAILS"
    exit 1
fi
