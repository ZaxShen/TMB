#!/usr/bin/env bash
set -euo pipefail

echo
echo "  🤙  Installing Trust My Bot..."
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
echo "  Installing trustmybot..."
uv tool install --upgrade trustmybot 2>&1 | tail -3
echo

echo "  ✅ Done! Run 'bot' in your project directory:"
echo
echo "     cd your-project/"
echo "     bot                    # first run walks you through setup"
echo "     bot \"fix the login\"    # quick task"
echo
echo "  Alias: 'bro' also works."
echo
