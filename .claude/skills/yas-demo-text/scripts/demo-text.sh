#!/usr/bin/env bash
# Strip every `make demo/img` snapshot under demo/ into colour-free plain text
# under demo/text/, mirroring the demo/ layout (top-level scenarios + themes/).
# Run `make demo/img` (optionally DEMO_ONLY=<scenario>) first so demo/*.txt are
# fresh. Both demo/ and demo/text/ are gitignored scratch artifacts.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(git -C "$here" rev-parse --show-toplevel)"
cd "$root"

if [ ! -d demo ]; then
  echo "no demo/ dir — run 'make demo/img' first" >&2
  exit 1
fi

count=0
while IFS= read -r f; do
  dest="demo/text/${f#demo/}"
  mkdir -p "$(dirname "$dest")"
  bash "$here/strip-ansi.sh" "$f" > "$dest"
  count=$((count + 1))
done < <(find demo -name '*.txt' -not -path 'demo/text/*')

echo "wrote $count file(s) to demo/text/"
