#!/usr/bin/env bash
# Render before/after PNGs for one or more demo variants and stage them into a
# local checkout of the yas-pr-screenshots repo, then print a markdown table.
#
#   shoot.sh <pr_id> <screenshots_repo_dir> <variant>...
#
# variant = LABEL:SCENARIO:ENV      (ENV optional)
#   LABEL     basename for the png + table row id        (e.g. narrow)
#   SCENARIO  ops/demo.py scenario name                  (e.g. kitchen-sink)
#   ENV       space-separated YAS_* knobs, may be empty  (e.g. 'YAS_MAX_WIDTH=40')
#
# Example:
#   shoot.sh 79 ../yas-pr-screenshots \
#     'kitchen-sink:kitchen-sink:' \
#     'narrow:kitchen-sink:YAS_MAX_WIDTH=40' \
#     'subagents:subagents:'
#
# "after"  = current working tree (the branch).
# "before" = main, rendered in a throwaway git worktree.
# A before render that fails (e.g. a scenario new to this branch) leaves the
# before cell empty rather than aborting.
set -euo pipefail

[ $# -ge 3 ] || { echo "usage: shoot.sh <pr_id> <screenshots_repo_dir> <variant>..." >&2; exit 2; }

pr_id=$1; repo=$2; shift 2
yas_root=$(git rev-parse --show-toplevel)
repo=$(cd "$repo" && pwd)
owner_repo='tmck-code/yas-pr-screenshots'
url_base="https://github.com/$owner_repo/blob/main/screenshots/$pr_id"

before_dir="$repo/screenshots/$pr_id/before"
after_dir="$repo/screenshots/$pr_id/after"
mkdir -p "$before_dir" "$after_dir"

wt="$(mktemp -d)/yas-base"
git -C "$yas_root" worktree add -q "$wt" main
trap 'git -C "$yas_root" worktree remove --force "$wt" >/dev/null 2>&1 || true' EXIT

render() { # <tree-dir> <scenario> <env> <out-png>
  ( cd "$1" && env $3 DEMO_ONLY="$2" make demo/img >/dev/null 2>&1 ) && cp "$1/demo/$2.png" "$4"
}

rows=()
for variant in "$@"; do
  IFS=: read -r label scenario env <<< "$variant"
  echo ">> $label  (scenario=$scenario${env:+ env=$env})" >&2

  render "$yas_root" "$scenario" "$env" "$after_dir/$label.png" \
    || { echo "   ERROR: after render failed for $label" >&2; exit 1; }

  if render "$wt" "$scenario" "$env" "$before_dir/$label.png"; then
    before_cell="![${label} before]($url_base/before/$label.png?raw=true)"
  else
    echo "   note: before render failed on main (new to this branch?) — empty cell" >&2
    before_cell=""
  fi
  rows+=("| $before_cell | ![${label} after]($url_base/after/$label.png?raw=true) |")
done

# Markdown table on stdout — this is the handoff artifact.
echo
echo "| before | after |"
echo "|--------|-------|"
printf '%s\n' "${rows[@]}"
