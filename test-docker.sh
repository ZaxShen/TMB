#!/usr/bin/env bash
set -euo pipefail

# Test bro install + setup in a clean environment (no Python, no uv)
# Usage:
#   ./test-docker.sh              # test dev branch
#   ./test-docker.sh stable       # test PyPI release
#   ./test-docker.sh interactive  # drop into shell to test manually

CHANNEL="${1:-dev}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cat <<'DOCKERFILE' > /tmp/bro-test.Dockerfile
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Nothing else — no Python, no uv, no pip
# get-bro.sh should handle everything

# Ensure uv/tool binaries are in PATH across all layers and docker run
ENV PATH="/root/.local/bin:${PATH}"

# Use local get-bro.sh for testing (not the remote one on GitHub)
COPY get-bro.sh /tmp/get-bro.sh
RUN sh /tmp/get-bro.sh

RUN mkdir /project && cd /project && git init

# Verify all three aliases work
RUN bro --version && bot --version && tmb --version

WORKDIR /project
DOCKERFILE

# Copy local get-bro.sh to build context
cp "${SCRIPT_DIR}/get-bro.sh" /tmp/get-bro.sh

echo
echo "  🧪 Building test image (${CHANNEL} channel)..."
echo

docker build \
    --no-cache \
    -t "bro-test-${CHANNEL}" \
    -f /tmp/bro-test.Dockerfile \
    /tmp

echo
echo "  ✅ Image built: bro-test-${CHANNEL}"
echo

if [ "$CHANNEL" = "interactive" ]; then
    echo "  Dropping into shell — test manually:"
    echo "    bro --version"
    echo "    bro upgrade"
    echo "    bro"
    echo
    docker run -it --rm "bro-test-dev" /bin/bash
else
    echo "  --- bro --version ---"
    docker run --rm "bro-test-${CHANNEL}" bro --version
    echo
    echo "  --- bro upgrade ---"
    docker run --rm "bro-test-${CHANNEL}" bro upgrade
    echo
    echo "  🧪 For interactive testing:"
    echo "    docker run -it --rm bro-test-${CHANNEL} /bin/bash"
    echo
fi
