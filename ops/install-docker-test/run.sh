#!/usr/bin/env bash
# run.sh — HOST-side driver for the install.sh Docker verification harness.
#
# Runs container-test.sh inside the STOCK ghcr.io/tmck-code/claude-container:python
# image (no Dockerfile / no build step — jq is gone, so no augmentation is needed)
# against a read-only mount of this repo. Forwards the container's exit code so CI
# can gate on it.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

IMAGE="ghcr.io/tmck-code/claude-container:python"

printf '== Pulling stock image (%s) ==\n' "$IMAGE"
docker pull "$IMAGE"

printf '\n== Running container test ==\n'
# Network is left ON (default): the uv bootstrap + `uv python install 3.15` need
# to download the official installer and CPython.
set +e
docker run --rm \
    -v "$REPO_ROOT":/repo:ro \
    -w /app \
    "$IMAGE" \
    bash /repo/ops/install-docker-test/container-test.sh
RC=$?
set -e

if [ "$RC" -eq 0 ]; then
    printf '\n=== INSTALL DOCKER TEST: PASS ===\n'
else
    printf '\n=== INSTALL DOCKER TEST: FAIL (exit %d) ===\n' "$RC"
fi
exit "$RC"
