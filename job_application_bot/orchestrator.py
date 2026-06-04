"""Stable orchestration facade while legacy implementation migrates out of main."""

from __future__ import annotations

from typing import Any


async def orchestrate_application(*args: Any, **kwargs: Any) -> Any:
    """Run the application workflow through the current legacy orchestrator."""
    from main import orchestrate_application as legacy_orchestrate_application

    return await legacy_orchestrate_application(*args, **kwargs)
