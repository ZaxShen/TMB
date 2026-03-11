"""Backward-compatible shim — delegates to tmb.cli.main().

Prefer running ``uv run tmb`` from the project root instead.
"""
from tmb.cli import main

if __name__ == "__main__":
    main()
