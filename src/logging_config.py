"""Logging configuration for audio-to-subs.

Provides structured logging setup with configurable verbosity levels.
"""

import logging
import sys


def configure_logging(verbose: bool = False) -> None:
    """Configure Python logging for audio-to-subs.

    Args:
        verbose: Enable DEBUG level logging for detailed output.
                If False, uses INFO level for normal operation.
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = (
        "[%(levelname)s] %(name)s: %(message)s"
        if verbose
        else "[%(levelname)s] %(message)s"
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
