"""TCS RFP Response Drafter package."""

from __future__ import annotations

from typing import Any

__all__ = ["agent", "app"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .agent import agent, app

        return {"agent": agent, "app": app}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
