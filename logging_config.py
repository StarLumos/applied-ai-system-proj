"""Logging setup for PawPal+.

All modules log under the ``pawpal`` namespace (``pawpal.rag``, ``pawpal.suggestions``,
``pawpal.app``). ``setup_logging()`` sends those records to the console and to a rotating
file, ``logs/pawpal.log``. The level comes from the ``PAWPAL_LOG_LEVEL`` environment
variable (default INFO; use DEBUG to see every retrieval query and skipped task).

What is logged: events, counts, species, life stage, guide ids and error details. What is
not logged at INFO or above: pet names, owner names or task descriptions you typed. The
DEBUG level can include retrieval queries and guide task names, so keep it for development.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

LOGGER_NAME = "pawpal"
LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE_NAME = "pawpal.log"
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3


def setup_logging(level: Optional[str] = None, log_dir: Optional[Path] = None) -> logging.Logger:
    """Configure the ``pawpal`` logger once and return it. Safe to call repeatedly.

    The log folder is ``log_dir``, else the ``PAWPAL_LOG_DIR`` environment variable, else
    ``logs/`` next to this file.

    Streamlit re-runs the script on every click, so calling this on each run must not add
    duplicate handlers. If the log file can't be opened (read-only folder, no permission)
    the app keeps running with console logging only.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_pawpal_configured", False):
        return logger

    requested = (level or os.environ.get("PAWPAL_LOG_LEVEL") or "INFO").upper()
    resolved = logging.getLevelName(requested)
    bad_level = not isinstance(resolved, int)
    logger.setLevel(logging.INFO if bad_level else resolved)

    formatter = logging.Formatter(FORMAT)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    folder = Path(log_dir or os.environ.get("PAWPAL_LOG_DIR") or LOG_DIR)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            folder / LOG_FILE_NAME, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("File logging disabled (%s); logging to the console only.", exc)

    if bad_level:
        logger.warning("Unknown PAWPAL_LOG_LEVEL %r; using INFO.", requested)
    logger._pawpal_configured = True  # type: ignore[attr-defined]
    return logger


def reset_logging() -> None:
    """Remove every handler and the configured flag (used by tests to start clean)."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger._pawpal_configured = False  # type: ignore[attr-defined]
