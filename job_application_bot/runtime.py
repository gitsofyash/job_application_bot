"""Runtime path helpers for future production deployment boundaries."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_data_dir(default: Path) -> Path:
    """Return the runtime data directory, overridable outside the repository."""
    configured = os.getenv("JOB_BOT_DATA_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else default


def resolve_output_dir(default: Path) -> Path:
    """Return the generated-artifact directory, overridable outside the repository."""
    configured = os.getenv("JOB_BOT_OUTPUT_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else default
