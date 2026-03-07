"""Backward-compatible shim — delegates to baymax.cli.main().

Prefer running ``uv run baymax`` from the project root instead.
"""
from baymax.cli import main

if __name__ == "__main__":
    main()
