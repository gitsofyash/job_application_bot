"""Configuration package for job application bot"""

from .settings import (
    PROJECT_ROOT,
    OUTPUT_DIR,
    DATA_DIR,
    LLM_PROVIDER,
    DRY_RUN,
    DEBUG,
    VERIFIED_SKILLS,
)

__all__ = [
    "PROJECT_ROOT",
    "OUTPUT_DIR",
    "DATA_DIR",
    "LLM_PROVIDER",
    "DRY_RUN",
    "DEBUG",
    "VERIFIED_SKILLS",
]
