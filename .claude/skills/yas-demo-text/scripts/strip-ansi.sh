#!/usr/bin/env bash
# Strip ANSI/CSI escape sequences from text, leaving box-drawing, Nerd Font
# glyphs and column layout intact.
#
# Source - https://stackoverflow.com/a/51141872
# Posted by meustrus, modified by community. See post 'Timeline' for change history
# Retrieved 2026-06-18, License - CC BY-SA 4.0
#
# Usage:
#   ./strip-ansi.sh < input.txt        # filter stdin -> stdout
#   ./strip-ansi.sh file [file ...]    # strip the named files -> stdout
set -euo pipefail

sed 's/\x1B\[[0-9;]\{1,\}[A-Za-z]//g' "$@"
