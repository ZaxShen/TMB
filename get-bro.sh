#!/bin/sh
set -eu

# ── Channel ──────────────────────────────────────────────
# No argument  → install from PyPI (stable release)
# Branch name  → install from that git branch:
#   curl ... | sh              (stable from PyPI)
#   curl ... | sh -s -- dev    (dev branch from git)
#   curl ... | sh -s -- main   (main branch from git)
CHANNEL="${1:-stable}"

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
if [ "$CHANNEL" = "stable" ]; then
    echo "  Installing trustmybot (stable from PyPI)..."
    if ! uv tool install --upgrade trustmybot; then
        echo "  ERROR: Failed to install trustmybot from PyPI."
        exit 1
    fi
else
    echo "  Installing trustmybot ($CHANNEL branch from git)..."
    if ! uv tool install --upgrade --reinstall --from "git+https://github.com/ZaxShen/TMB@$CHANNEL" trustmybot; then
        echo "  ERROR: Failed to install trustmybot from $CHANNEL."
        exit 1
    fi
fi
echo

# 3. Ensure tool bin dir is in PATH for future shells
# Use uv's actual tool bin dir (not hardcoded — may differ per platform)
TOOL_BIN=$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")
case ":${PATH}:" in
    *":$TOOL_BIN:"*) ;;
    *) export PATH="$TOOL_BIN:$PATH" ;;
esac

# Detect user's shell and target the right profile file
_ensure_path_in_profile() {
    _profile="$1"
    # Create the file if it doesn't exist — otherwise PATH is never persisted
    if [ ! -f "$_profile" ]; then
        touch "$_profile"
    fi
    if ! grep -q "$TOOL_BIN" "$_profile" 2>/dev/null; then
        printf '\n# Added by Trust My Bot installer\nexport PATH="%s:$PATH"\n' "$TOOL_BIN" >> "$_profile"
    fi
}

# Detect current shell — target the right rc file
CURRENT_SHELL=$(basename "${SHELL:-/bin/sh}" 2>/dev/null || echo "sh")
case "$CURRENT_SHELL" in
    zsh)
        _ensure_path_in_profile "$HOME/.zshrc"
        ;;
    bash)
        _ensure_path_in_profile "$HOME/.bashrc"
        # macOS bash also reads .bash_profile for login shells (Terminal.app)
        if [ "$(uname)" = "Darwin" ]; then
            _ensure_path_in_profile "$HOME/.bash_profile"
        fi
        ;;
    *)
        _ensure_path_in_profile "$HOME/.profile"
        ;;
esac

# Also ensure .zshrc on macOS since it's the default shell (even if user is in bash now)
if [ "$(uname)" = "Darwin" ] && [ "$CURRENT_SHELL" != "zsh" ]; then
    _ensure_path_in_profile "$HOME/.zshrc"
fi

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
    echo
    echo "  ⚠️  If this is a fresh install, restart your terminal first."
else
    echo "  ✅ Installed! To start using it:"
    echo
    echo "     1. Restart your terminal (or run: source ~/.${CURRENT_SHELL}rc)"
    echo "     2. Then:"
    echo "        cd your-project/"
    echo "        bot                 # first run walks you through setup"
    echo
fi
echo
