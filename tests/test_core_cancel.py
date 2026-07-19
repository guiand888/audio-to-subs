"""Tests for core/cancel.py module."""

import threading
import time

import pytest

from audio_to_subs.core.cancel import Cancelled, CancelToken


class TestCancelToken:
    """Tests for CancelToken class."""

    def test_initial_state(self) -> None:
        """Test that a new token is not set."""
        token = CancelToken()
        assert token.is_set() is False

    def test_set(self) -> None:
        """Test setting the token."""
        token = CancelToken()
        token.set()
        assert token.is_set() is True

    def test_clear(self) -> None:
        """Test clearing the token."""
        token = CancelToken()
        token.set()
        assert token.is_set() is True
        token.clear()
        assert token.is_set() is False

    def test_check_not_set(self) -> None:
        """Test check() when token is not set."""
        token = CancelToken()
        # Should not raise
        token.check()

    def test_check_set(self) -> None:
        """Test check() when token is set."""
        token = CancelToken()
        token.set()
        with pytest.raises(Cancelled):
            token.check()

    def test_thread_safety(self) -> None:
        """Test that token is thread-safe."""
        token = CancelToken()
        errors = []

        def set_token() -> None:
            try:
                time.sleep(0.1)
                token.set()
            except Exception as e:
                errors.append(e)

        def check_token() -> None:
            try:
                for _ in range(10):
                    token.check()
                    time.sleep(0.05)
            except Cancelled:
                pass
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=set_token),
            threading.Thread(target=check_token),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_multiple_sets(self) -> None:
        """Test that multiple set() calls are idempotent."""
        token = CancelToken()
        token.set()
        token.set()
        token.set()
        assert token.is_set() is True


class TestCancelled:
    """Tests for Cancelled exception."""

    def test_is_exception(self) -> None:
        """Test that Cancelled is an Exception."""
        assert issubclass(Cancelled, Exception)

    def test_message(self) -> None:
        """Test that Cancelled can carry a message."""
        exc = Cancelled("Test message")
        assert str(exc) == "Test message"

    def test_no_message(self) -> None:
        """Test Cancelled without a message."""
        exc = Cancelled()
        assert str(exc) == ""
