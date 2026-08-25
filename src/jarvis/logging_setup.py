"""Logging.

A bundled .app has no terminal, so file logging is the only way to find out what
happened. Console output stays on when running from source.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(threadName)-14s %(name)-28s %(message)s"
_DATEFMT = "%H:%M:%S"


def configure(log_dir: Path, level: str = "INFO", console: bool = True) -> Path:
    """Set up root logging. Returns the log file path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "jarvis.log"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console and sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    # These are chatty at DEBUG and never interesting.
    for noisy in ("urllib3", "httpx", "httpcore", "PIL", "comtypes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_file
