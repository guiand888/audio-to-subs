"""Cancellation support for pipeline operations.

Provides CancelToken for cooperative cancellation of long-running operations.
"""

import threading


class Cancelled(Exception):
    """Raised when a CancelToken has been set.

    This exception is raised by CancelToken.check() when cancellation
    has been requested via CancelToken.set().
    """

    pass


class CancelToken:
    """Thread-safe cancellation token for cooperative cancellation.

    Usage:
        token = CancelToken()

        # In the operation being cancelled:
        def long_operation(token: CancelToken):
            for chunk in chunks:
                token.check()  # Raises Cancelled if set
                process(chunk)

        # In the cancelling code:
        token.set()  # Signals cancellation
    """

    def __init__(self) -> None:
        """Initialize a new CancelToken."""
        self._event = threading.Event()

    def set(self) -> None:
        """Signal that cancellation has been requested.

        After calling this method, check() will raise Cancelled.
        This method is thread-safe and idempotent.
        """
        self._event.set()

    def is_set(self) -> bool:
        """Check if cancellation has been requested.

        Returns:
            True if set() has been called, False otherwise.
        """
        return self._event.is_set()

    def check(self) -> None:
        """Raise Cancelled if cancellation has been requested.

        Raises:
            Cancelled: If set() has been called on this token.
        """
        if self._event.is_set():
            raise Cancelled

    def clear(self) -> None:
        """Clear the cancellation signal.

        After calling this method, is_set() will return False and check()
        will not raise Cancelled until set() is called again.
        """
        self._event.clear()
