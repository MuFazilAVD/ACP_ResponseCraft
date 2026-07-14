"""ASGI entry point for the TCS RFP Response Drafter."""

# Configure logging BEFORE importing the agent so every module gets the
# correct handlers from the very first import.
from .logging_utils import setup_logging

setup_logging()

from .agent import app  # noqa: E402

__all__ = ["app"]
