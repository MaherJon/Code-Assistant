"""Structured logging setup for MAHE."""

import logging
import os
import sys
from datetime import datetime


def setup_logging(level: str = "INFO", log_file: str = None) -> logging.Logger:
    """Configure logging for MAHE.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional log file path (default: ~/.mahe/mahe.log)

    Returns:
        Configured root logger for MAHE
    """
    logger = logging.getLogger("mahe")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Console handler (warnings and above only, to not clutter terminal)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.WARNING)
    console_fmt = logging.Formatter(
        "[%(levelname)s] %(message)s"
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # File handler (all levels)
    if log_file is None:
        log_dir = os.path.expanduser("~/.mahe")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "mahe.log")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "mahe") -> logging.Logger:
    """Get a logger for a specific module."""
    return logging.getLogger(name)
