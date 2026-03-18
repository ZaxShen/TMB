#!/bin/sh
set -eu

# ── Channel ──────────────────────────────────────────────
# "stable" = PyPI release   (main branch)
# "dev"    = latest dev      (dev branch, installed from git)
CHANNEL="dev"

echo
echo "  🤙  Installing Trust My Bot ($CHANNEL)..."
echo

# Ensure ~/.local/bin is in PATH (where uv puts tool binaries)
case ":${PATH}:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

# 1. Install uv if missing
if ! command -v uv >/dev/null 2>&1; then
    echo "  Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    if ! command -v uv >/dev/null 2>&1; then
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
    if ! uv tool install --upgrade --reinstall --from "git+https://github.com/ZaxShen/TMB@dev" trustmybot; then
        echo "  ERROR: Failed to install trustmybot from dev."
        exit 1
    fi
else
    echo "  Installing trustmybot (stable)..."
    if ! uv tool install --upgrade trustmybot; then
        echo "  ERROR: Failed to install trustmybot."
        exit 1
    fi
fi
echo

# 3. Ensure tool bin is in PATH for future shells
TOOL_BIN="$HOME/.local/bin"
_ensure_path_in_profile() {
    _profile="$1"
    if [ -f "$_profile" ]; then
        if ! grep -q "/.local/bin" "$_profile" 2>/dev/null; then
            printf '\n# Added by Trust My Bot installer\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$_profile"
        fi
    fi
}
_ensure_path_in_profile "$HOME/.bashrc"
_ensure_path_in_profile "$HOME/.zshrc"
# Also .profile for non-interactive login shells (Docker, cron, etc.)
_ensure_path_in_profile "$HOME/.profile"

# 4. Verify installation
if command -v bro >/dev/null 2>&1; then
    echo "  ✅ Done! Run 'bot' in your project directory:"
    echo
    echo "     cd your-project/"
    echo "     bot                    # first run walks you through setup"
    echo "     bot \"fix the login\"    # quick task"
    echo
    echo "  Aliases: 'bro' and 'tmb' also work."
    echo "  Upgrade anytime: bro upgrade"
else
    echo "  ✅ Installed! But 'bro' isn't in your current PATH."
    echo
    echo "  Restart your terminal, then run:"
    echo
    echo "     cd your-project/"
    echo "     bot                    # first run walks you through setup"
    echo
    echo "  Or run this now:  export PATH=\"$TOOL_BIN:\$PATH\""
fi
echo
