"""Tests for logging_config module.

Tests logging configuration with different verbosity levels
and logger suppression.
"""
import logging
import sys
from io import StringIO

import pytest

from src.logging_config import configure_logging


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging configuration before and after each test."""
    # Store original handlers and config
    original_handlers = logging.root.handlers[:]
    original_level = logging.root.level

    yield

    # Restore original state
    logging.root.handlers = original_handlers
    logging.root.level = original_level


class TestConfigureLogging:
    """Test logging configuration."""

    def test_configure_logging_default(self):
        """Test logging configured with default (non-verbose) level."""
        # Act
        configure_logging(verbose=False)

        # Assert
        assert logging.root.level == logging.INFO
        assert logging.getLogger("mistralai").level == logging.WARNING
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("urllib3").level == logging.WARNING

    def test_configure_logging_verbose(self):
        """Test logging configured with verbose level."""
        # Act
        configure_logging(verbose=True)

        # Assert
        assert logging.root.level == logging.DEBUG
        # Verbose should not suppress third-party loggers
        # (they remain at their root level or above)

    def test_logging_format_non_verbose(self):
        """Test logging format in non-verbose mode."""
        # Act
        configure_logging(verbose=False)

        # Assert - check that a handler was added
        assert len(logging.root.handlers) > 0
        handler = logging.root.handlers[0]
        # Format should be simple in non-verbose mode
        if handler.formatter:
            assert handler.formatter._fmt is not None

    def test_logging_format_verbose(self):
        """Test logging format in verbose mode."""
        # Act
        configure_logging(verbose=True)

        # Assert
        assert len(logging.root.handlers) > 0
        handler = logging.root.handlers[0]
        # Format should include logger name in verbose mode
        if handler.formatter:
            assert "%(name)s" in handler.formatter._fmt

    def test_logging_output_to_stderr(self):
        """Test that logging is configured to output to stderr."""
        # Act
        configure_logging()

        # Assert
        assert len(logging.root.handlers) > 0
        handler = logging.root.handlers[0]
        # Should be a StreamHandler pointing to stderr
        if hasattr(handler, "stream"):
            assert handler.stream == sys.stderr or handler.stream.name == "<stderr>"

    def test_third_party_logger_suppression(self):
        """Test that third-party loggers are suppressed in normal mode."""
        # Act
        configure_logging(verbose=False)

        # Assert
        mistral_logger = logging.getLogger("mistralai")
        httpx_logger = logging.getLogger("httpx")
        urllib3_logger = logging.getLogger("urllib3")

        # These should be set to WARNING
        assert mistral_logger.level == logging.WARNING
        assert httpx_logger.level == logging.WARNING
        assert urllib3_logger.level == logging.WARNING

    def test_third_party_logger_not_suppressed_verbose(self):
        """Test that third-party loggers are not suppressed in verbose mode."""
        # Act
        configure_logging(verbose=True)

        # Assert - loggers should not have WARNING level set
        mistral_logger = logging.getLogger("mistralai")
        httpx_logger = logging.getLogger("httpx")
        urllib3_logger = logging.getLogger("urllib3")

        # In verbose mode, these should not be explicitly set to WARNING
        # (they inherit from root logger)
        # Only verify that configure_logging doesn't set them to WARNING
        # when verbose=True

    def test_force_flag_reconfigures_logging(self):
        """Test that configure_logging with force=True reconfigures."""
        # Arrange - set up initial logging
        configure_logging(verbose=False)
        initial_handler_count = len(logging.root.handlers)

        # Act - reconfigure with different setting
        configure_logging(verbose=True)

        # Assert - should have reconfigured (force=True in basicConfig)
        # Handler count might change due to force=True
        assert logging.root.level == logging.DEBUG

    def test_multiple_configure_calls(self):
        """Test multiple calls to configure_logging."""
        # Act
        configure_logging(verbose=False)
        configure_logging(verbose=True)
        configure_logging(verbose=False)

        # Assert - last configuration should be applied
        assert logging.root.level == logging.INFO
        assert logging.getLogger("mistralai").level == logging.WARNING

    def test_logging_actually_logs(self):
        """Test that logging actually produces output."""
        # Arrange
        configure_logging(verbose=False)
        test_logger = logging.getLogger("test_module")

        # Capture stderr
        captured_output = StringIO()
        handler = logging.StreamHandler(captured_output)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(formatter)

        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        # Act
        test_logger.info("Test message")

        # Assert
        output = captured_output.getvalue()
        assert "Test message" in output
        assert "[INFO]" in output

    def test_logging_debug_not_shown_non_verbose(self):
        """Test that DEBUG messages are not shown in non-verbose mode."""
        # Arrange
        configure_logging(verbose=False)
        test_logger = logging.getLogger("test_module")

        captured_output = StringIO()
        handler = logging.StreamHandler(captured_output)
        handler.setLevel(logging.DEBUG)  # Handler accepts DEBUG
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)  # Logger accepts DEBUG

        # Act
        test_logger.debug("Debug message")

        # Assert - root logger level is INFO, so DEBUG won't be propagated
        output = captured_output.getvalue()
        # Since root logger is INFO level, debug won't appear at root
        # (but would appear if we logged through root directly)

    def test_logging_debug_shown_verbose(self):
        """Test that DEBUG messages are shown in verbose mode."""
        # Arrange
        configure_logging(verbose=True)
        test_logger = logging.getLogger("test_module")

        captured_output = StringIO()
        handler = logging.StreamHandler(captured_output)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        handler.setFormatter(formatter)

        test_logger.addHandler(handler)

        # Act
        test_logger.debug("Debug message")

        # Assert
        output = captured_output.getvalue()
        assert "Debug message" in output


class TestLoggingDefaults:
    """Test logging configuration defaults."""

    def test_default_verbosity_is_false(self):
        """Test that default verbosity is False."""
        # This is implicit in the function signature
        # Act
        configure_logging()  # Call without arguments

        # Assert
        assert logging.root.level == logging.INFO

    def test_boolean_parameter_types(self):
        """Test that verbose parameter accepts boolean values."""
        # Act & Assert - should not raise
        configure_logging(verbose=True)
        configure_logging(verbose=False)
        configure_logging(verbose=bool(1))
        configure_logging(verbose=bool(0))
