"""Session management using itsdangerous.

Signed cookies for stateless authentication.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any

from itsdangerous import URLSafeTimedSerializer
from itsdangerous.exc import BadSignature, SignatureExpired

logger = logging.getLogger(__name__)

# Default session TTL: 30 days in seconds
DEFAULT_SESSION_TTL = 30 * 24 * 3600
# Sliding renewal threshold: 1 hour in seconds
SLIDING_RENEWAL_THRESHOLD = 3600
# Default session cookie name
SESSION_COOKIE_NAME = "ats_session"
# Default session secret file path
DEFAULT_SESSION_SECRET_FILE = "/data/session_secret"
# Placeholder secret to refuse
PLACEHOLDER_SECRET = "changeme"


class SessionManager:
    """Manages session creation and validation."""

    def __init__(
        self,
        secret: str | None = None,
        secret_file: str | None = None,
        salt: str | None = None,
        ttl: int = DEFAULT_SESSION_TTL,
    ):
        """Initialize session manager.
        
        Args:
            secret: Session secret string
            secret_file: Path to file containing secret
            salt: Salt for serializer
            ttl: Session TTL in seconds
        """
        # Determine secret
        if secret is not None:
            self._secret = secret
        elif secret_file is not None:
            self._secret = self._read_secret_file(secret_file)
        else:
            self._secret = self._read_secret_file(DEFAULT_SESSION_SECRET_FILE)

        # Validate secret is not placeholder
        if self._secret == PLACEHOLDER_SECRET:
            raise ValueError(
                "Refusing to start with default placeholder session secret. "
                "Set SESSION_SECRET or SESSION_SECRET_FILE to a real secret."
            )

        # Generate salt if not provided
        if salt is None:
            salt = "audio-to-subs-session"

        self._serializer = URLSafeTimedSerializer(
            self._secret, salt=salt, signer_kwargs={"key_derivation": "hmac"}
        )
        self._ttl = ttl

    @staticmethod
    def _read_secret_file(path: str) -> str:
        """Read secret from file."""
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            # File doesn't exist yet - will be created on first boot
            return PLACEHOLDER_SECRET

    @staticmethod
    def generate_secret() -> str:
        """Generate a new random session secret."""
        import secrets

        return secrets.token_urlsafe(64)

    @staticmethod
    def write_secret_file(path: str, secret: str | None = None) -> str:
        """Write session secret to file.
        
        Args:
            path: Path to write secret to
            secret: Secret to write (generates new if None)
        
        Returns:
            The secret that was written
        """
        if secret is None:
            secret = SessionManager.generate_secret()

        # Ensure directory exists
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        # Write with restrictive permissions (owner read/write only)
        old_umask = os.umask(0o077)
        try:
            with open(path, "w") as f:
                f.write(secret)
        finally:
            os.umask(old_umask)

        return secret

    def create_session(self, user_id: int) -> str:
        """Create a new session token.
        
        Args:
            user_id: User ID to include in session
        
        Returns:
            Signed session token string
        """
        payload = {"user_id": user_id, "iat": int(time.time())}
        return self._serializer.dumps(payload)

    def validate_session(self, token: str, max_age: int | None = None) -> dict[str, Any]:
        """Validate and decode a session token.
        
        Args:
            token: Session token string
            max_age: Maximum age in seconds (uses TTL if None)
        
        Returns:
            Decoded payload dictionary
        
        Raises:
            BadSignature: If token signature is invalid
            SignatureExpired: If token has expired
        """
        if max_age is None:
            max_age = self._ttl
        return self._serializer.loads(token, max_age=max_age)

    def needs_renewal(self, payload: dict[str, Any]) -> bool:
        """Check if session needs sliding renewal.
        
        Args:
            payload: Decoded session payload
        
        Returns:
            True if session should be renewed
        """
        iat = payload.get("iat", 0)
        return (time.time() - iat) > SLIDING_RENEWAL_THRESHOLD

    def renew_session(self, token: str) -> str:
        """Renew a session token.
        
        Args:
            token: Current session token
        
        Returns:
            New session token with updated iat
        """
        payload = self._serializer.loads(token, max_age=self._ttl)
        payload["iat"] = int(time.time())
        return self._serializer.dumps(payload)


# Global session manager instance (lazy initialization)
_session_manager: SessionManager | None = None


def get_session_manager(
    secret: str | None = None,
    secret_file: str | None = None,
) -> "SessionManager":
    """Get or create session manager singleton.

    When called with no arguments the function falls back to the
    ``SESSION_SECRET`` / ``SESSION_SECRET_FILE`` environment variables so
    that routes, tests, and the lifespan all obtain a consistent instance
    without needing to pass settings around manually.

    IMPORTANT: All calls should use consistent secret parameters. If the
    first call uses default env vars and a later call passes explicit
    parameters, the explicit parameters are IGNORED and the env-based
    instance is returned.

    Args:
        secret: Explicit session secret string.
        secret_file: Path to a file containing the session secret.

    Returns:
        The cached ``SessionManager`` instance.
    """
    global _session_manager
    if _session_manager is None:
        # Fall back to env vars when no explicit values are given.
        if secret is None and secret_file is None:
            secret = os.environ.get("SESSION_SECRET")
            secret_file = os.environ.get("SESSION_SECRET_FILE")
        _session_manager = SessionManager(
            secret=secret,
            secret_file=secret_file,
        )
    else:
        # Log if caller is trying to create with different parameters
        if secret is not None or secret_file is not None:
            logger.debug(
                "SessionManager already initialized; ignoring provided secret parameters"
            )
    return _session_manager
