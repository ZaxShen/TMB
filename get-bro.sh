#!/usr/bin/env bash
set -euo pipefail

# ── Channel ──────────────────────────────────────────────
# "stable" = PyPI release   (main branch)
# "dev"    = latest dev      (dev branch, installed from git)
CHANNEL="dev"

echo
echo "  🤙  Installing Trust My Bot ($CHANNEL)..."
echo

# 1. Install uv if missing
if ! command -v uv &> /dev/null; then
    echo "  Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &> /dev/null; then
        echo "  ERROR: Failed to install uv."
        echo "  Install manually: https://docs.astral.sh/uv/"
        exit 1
    fi
    echo "  uv installed."
    echo
fi

# 2. Install trustmybot globally
if [ "$CHANNEL" = "dev" ]; then
    echo "  Installing trustmybot (dev branch)..."
    uv tool install --upgrade --reinstall --from "git+https://github.com/ZaxShen/TMB@dev" trustmybot 2>&1 | tail -3
else
    echo "  Installing trustmybot (stable)..."
    uv tool install --upgrade trustmybot 2>&1 | tail -3
fi
echo

echo "  ✅ Done! Run 'bot' in your project directory:"
echo
echo "     cd your-project/"
echo "     bot                    # first run walks you through setup"
echo "     bot \"fix the login\"    # quick task"
echo
echo "  Alias: 'bro' also works."
echo "  Upgrade anytime: bro upgrade"
echo
