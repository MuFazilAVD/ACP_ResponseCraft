"""Centralised logging configuration for the TCS RFP Response Drafter agent.

Usage
-----
Call ``setup_logging()`` once at ASGI startup (see main.py), then obtain a
per-module logger with::

    from .logging_utils import get_logger
    logger = get_logger(__name__)

Log Files
---------
Logs are written to  ``<project_root>/logs/agent.log`` with rotating file
handler (10 MB per file, 5 backups).  A matching console handler writes to
``stderr`` so uvicorn's output stream stays clean.

Format
------
    2026-07-13 11:10:58,123 | INFO     | response_drafter_agent.agent | message

Visual section dividers are produced by ``log_section_start`` / ``log_section_end``
to make per-request boundaries easy to locate in the log file.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Project root is one level above the package directory.
_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_DIR.parent
LOGS_DIR = _PROJECT_ROOT / "logs"

_MAX_BYTES = 10 * 1024 * 1024   # 10 MB per file
_BACKUP_COUNT = 5                # keep backups

class ExactLevelFilter(logging.Filter):
    def __init__(self, level: int):
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self.level

class MinLevelFilter(logging.Filter):
    def __init__(self, level: int):
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.level

# ---------------------------------------------------------------------------
# Log format
# ---------------------------------------------------------------------------

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------------------
# Section divider helpers
# ---------------------------------------------------------------------------

_DIVIDER_WIDTH = 80
_DIVIDER_CHAR = "="


def log_section_start(logger: logging.Logger, title: str, **fields: Any) -> None:
    """Emit a visual section-start divider at INFO level.

    Example output::

        ================================================================================
         INVOKE START | conversation_id=abc-123 | model=gemini-2.5-flash-cto-lab
        ================================================================================
    """
    line = _DIVIDER_CHAR * _DIVIDER_WIDTH
    field_str = " | ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    body = f" {title}"
    if field_str:
        body = f"{body} | {field_str}"
    logger.info(line)
    logger.info(body)
    logger.info(line)


def log_section_end(logger: logging.Logger, title: str, **fields: Any) -> None:
    """Emit a visual section-end divider at INFO level."""
    line = _DIVIDER_CHAR * _DIVIDER_WIDTH
    field_str = " | ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    body = f" {title}"
    if field_str:
        body = f"{body} | {field_str}"
    logger.info(line)
    logger.info(body)
    logger.info(line)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Module-level flag so setup_logging() is truly idempotent even when uvicorn
# has already attached its own handlers to the root logger before importing us.
_configured: bool = False


def setup_logging(level: int | str = logging.DEBUG) -> None:
    """Configure the root logger with console and rotating-file handlers.

    Safe to call multiple times — only the first call does real work.

    **Why not use ``if root.handlers: return``?**
    Uvicorn installs its own ``StreamHandler`` on the root logger *before* it
    imports the application.  A naïve root-handler check would therefore return
    immediately on every real server startup, leaving the rotating file handler
    never attached and the log file empty after requests.  We use a
    module-level flag instead so the file handler is always added on the first
    genuine call, regardless of what uvicorn has already done.

    Parameters
    ----------
    level:
        Minimum log level for the *file* handler.  The console handler always
        uses ``INFO`` to avoid flooding the terminal during normal operation.
    """
    global _configured
    if _configured:
        return
    _configured = True

    # Ensure the logs directory exists.
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # ---- rotating file handlers for different levels -----------------------
    # Always attach – uvicorn's handlers are StreamHandlers, not file handlers,
    # so this is never a duplicate.
    levels_config = [
        (logging.DEBUG, "debug.log", ExactLevelFilter(logging.DEBUG)),
        (logging.INFO, "info.log", ExactLevelFilter(logging.INFO)),
        (logging.WARNING, "warning.log", ExactLevelFilter(logging.WARNING)),
        (logging.ERROR, "error.log", MinLevelFilter(logging.ERROR)),
    ]

    for lvl, filename, filt in levels_config:
        fh = logging.handlers.RotatingFileHandler(
            filename=LOGS_DIR / filename,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setLevel(lvl)
        fh.addFilter(filt)
        fh.setFormatter(formatter)
        root.addHandler(fh)

    # ---- console handler (INFO and above) ----------------------------------
    # Only add when no StreamHandler is present yet (e.g. running tests or a
    # plain `python -m` invocation).  Under uvicorn, the console handler is
    # already managed by uvicorn itself, so we skip adding a second one to
    # avoid duplicate lines in the terminal.
    has_stream_handler = any(
        type(h) is logging.StreamHandler  # exact type, not subclass
        for h in root.handlers
    )
    if not has_stream_handler:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    # Silence overly chatty third-party loggers at WARNING.
    for noisy in (
        "httpx",
        "httpcore",
        "urllib3",
        "opentelemetry",
        "langfuse",
        "langgraph",
        "langchain",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Announce that logging is live.
    _startup_logger = logging.getLogger("response_drafter_agent.logging_utils")
    _startup_logger.info(
        "Logging initialised | level=%s | log_dir=%s",
        logging.getLevelName(level),
        LOGS_DIR,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for the given module.

    Parameters
    ----------
    name:
        Typically ``__name__`` of the calling module.
    """
    return logging.getLogger(name)
