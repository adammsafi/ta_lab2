"""
Shared logging configuration for EMA refresh scripts.

Provides:
- Consistent log formatting across all scripts
- Configurable log levels (DEBUG, INFO, WARNING, ERROR)
- File and console output
- Process-safe logging for parallel execution
- Correlation IDs for tracking related operations
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


# Default format: timestamp, level, name, message
DEFAULT_FORMAT = "%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Detailed format for debugging (includes filename, line number)
DEBUG_FORMAT = (
    "%(asctime)s [%(levelname)-8s] [%(name)s] [%(filename)s:%(lineno)d] %(message)s"
)


def setup_logging(
    *,
    name: str,
    level: str = "INFO",
    log_file: Optional[str] = None,
    quiet: bool = False,
    debug: bool = False,
) -> logging.Logger:
    """
    Setup logging for an EMA refresh script.

    Args:
        name: Logger name (e.g., "ema_cal", "ema_anchor")
        level: Log level string (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional log file path
        quiet: If True, only show warnings and errors on console
        debug: If True, use detailed debug format

    Returns:
        Configured logger instance

    Example:
        logger = setup_logging(name="ema_cal", level="INFO")
        logger.info("Starting refresh...")
        logger.warning("No state found, running full history")
        logger.error("Failed to connect to database", exc_info=True)
    """
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Capture everything, filter at handler level
    logger.handlers.clear()  # Remove any existing handlers

    # Parse level
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if quiet:
        console_handler.setLevel(logging.WARNING)
    else:
        console_handler.setLevel(numeric_level)

    # Choose format based on debug flag
    log_format = DEBUG_FORMAT if debug else DEFAULT_FORMAT
    console_formatter = logging.Formatter(log_format, datefmt=DEFAULT_DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        file_formatter = logging.Formatter(DEBUG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        logger.info(f"Logging to file: {log_file}")

    return logger


def add_logging_args(parser) -> None:
    """
    Add standard logging arguments to an ArgumentParser.

    Args:
        parser: argparse.ArgumentParser instance

    Adds:
        --log-level: Set log level (DEBUG, INFO, WARNING, ERROR)
        --log-file: Optional log file path
        --quiet: Suppress console output except warnings/errors
        --debug: Enable detailed debug logging format
    """
    log_group = parser.add_argument_group("logging")

    log_group.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set log level (default: INFO)",
    )

    log_group.add_argument(
        "--log-file",
        default=None,
        help="Optional log file path (logs to console by default)",
    )

    log_group.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output except warnings and errors",
    )

    log_group.add_argument(
        "--debug",
        action="store_true",
        help="Enable detailed debug logging format with file/line info",
    )


def get_worker_logger(
    name: str,
    *,
    worker_id: Optional[str] = None,
    log_level: str = "INFO",
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    Create a process-safe logger for parallel worker processes.

    Args:
        name: Base logger name
        worker_id: Unique worker identifier (e.g., "worker-1-52-2D")
        log_level: Log level string
        log_file: Optional log file path

    Returns:
        Logger instance for this worker

    Note:
        Each worker gets its own logger to avoid interleaved output.
        The worker_id is included in the logger name for correlation.
    """
    if worker_id:
        logger_name = f"{name}.{worker_id}"
    else:
        logger_name = name

    return setup_logging(
        name=logger_name,
        level=log_level,
        log_file=log_file,
        quiet=False,
        debug=False,
    )


class LogContext:
    """
    Context manager for temporary log level changes.

    Example:
        with LogContext(logger, level=logging.DEBUG):
            # Detailed logging for this block
            logger.debug("Detailed info here")
    """

    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.new_level = level
        self.old_level = logger.level

    def __enter__(self):
        self.logger.setLevel(self.new_level)
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.setLevel(self.old_level)
        return False
