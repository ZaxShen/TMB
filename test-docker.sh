#!/usr/bin/env bash
set -euo pipefail

# Test bro install + setup in a clean environment (no Python, no uv)
# Usage:
#   ./test-docker.sh              # test dev branch
#   ./test-docker.sh stable       # test PyPI release
#   ./test-docker.sh interactive  # drop into shell to test manually

CHANNEL="${1:-dev}"

cat <<'DOCKERFILE' > /tmp/bro-test.Dockerfile
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Nothing else — no Python, no uv, no pip
# get-bro.sh should handle everything

ARG CHANNEL=dev
RUN curl -LsSf "https://raw.githubusercontent.com/ZaxShen/TMB/${CHANNEL}/get-bro.sh" | sh

RUN mkdir /project && cd /project && git init

WORKDIR /project
DOCKERFILE

echo
echo "  🧪 Building test image (${CHANNEL} channel)..."
echo

docker build \
    --build-arg "CHANNEL=${CHANNEL}" \
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
