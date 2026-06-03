"""Console helpers that keep CLI output readable across Windows encodings."""

from __future__ import annotations

from typing import Any

from rich.console import Console

from utils.url_parser import fix_encoding_issues


def _clean_renderable(value: Any) -> Any:
    if isinstance(value, str):
        return fix_encoding_issues(value)
    return value


class SafeConsole(Console):
    """Rich Console that sanitizes common mojibake before rendering strings."""

    def print(self, *objects: Any, **kwargs: Any) -> None:  # type: ignore[override]
        super().print(*(_clean_renderable(obj) for obj in objects), **kwargs)

    def log(self, *objects: Any, **kwargs: Any) -> None:  # type: ignore[override]
        kwargs["_stack_offset"] = int(kwargs.get("_stack_offset", 1)) + 1
        super().log(*(_clean_renderable(obj) for obj in objects), **kwargs)
