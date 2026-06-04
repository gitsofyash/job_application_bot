"""Package entrypoint for the existing CLI application."""

from __future__ import annotations

import asyncio


def run() -> None:
    """Execute the CLI maintained in the legacy main module."""
    from main import main as async_main

    asyncio.run(async_main())
