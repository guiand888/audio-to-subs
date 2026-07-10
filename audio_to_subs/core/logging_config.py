"""Logging configuration for audio-to-subs.

Provides structured logging setup with configurable verbosity levels.
"""

import logging
import os
import sys


def configure_logging(verbose: bool = False) -> None:
    """Configure Python logging for audio-to-subs.

    Args:
        verbose: Enable DEBUG level logging for detailed output.
                If False, uses INFO level for normal operation.
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = (
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        if verbose
        else "%(asctime)s [%(levelname)s] %(message)s"
    )

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        stream=sys.stderr,
        force=True,
    )

    # Suppress noisy third-party loggers unless in verbose mode
    if not verbose:
        logging.getLogger("mistralai").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)


def configure_logging_from_env() -> None:
    """Configure logging using the LOG_LEVEL environment variable.

    Entry point for long-running processes (API, worker) that have no
    interactive --verbose flag. LOG_LEVEL=DEBUG enables verbose logging;
    any other value (including unset) falls back to normal INFO-level
    operation. See configure_logging() for the underlying behavior.
    """
    verbose = os.environ.get("LOG_LEVEL", "INFO").strip().upper() == "DEBUG"
    configure_logging(verbose=verbose)
