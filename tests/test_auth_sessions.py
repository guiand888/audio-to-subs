"""Tests for session management."""

import os
import tempfile
import time

import pytest

from audio_to_subs.auth.sessions import (
    DEFAULT_SESSION_SECRET_FILE,
    PLACEHOLDER_SECRET,
    SessionManager,
    get_session_manager,
)


class TestSessionManagerInit:
    """Test SessionManager initialization."""

    def test_init_with_secret(self):
        """Test initialization with explicit secret."""
        secret = "test-secret-key"
        manager = SessionManager(secret=secret)
        assert manager._secret == secret

    def test_init_with_secret_file(self, tmp_path):
        """Test initialization with secret file."""
        secret_file = tmp_path / "secret.txt"
        secret = "test-secret-from-file"
        secret_file.write_text(secret)
        
        manager = SessionManager(secret_file=str(secret_file))
        assert manager._secret == secret

    def test_init_refuses_placeholder(self):
        """Test that initialization refuses placeholder secret."""
        with pytest.raises(ValueError, match="Refusing to start with default placeholder"):
            SessionManager(secret=PLACEHOLDER_SECRET)

    def test_init_refuses_placeholder_from_file(self, tmp_path):
        """Test that initialization refuses placeholder secret from file."""
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text(PLACEHOLDER_SECRET)
        
        with pytest.raises(ValueError, match="Refusing to start with default placeholder"):
            SessionManager(secret_file=str(secret_file))


class TestSessionManagerSecretFile:
    """Test secret file operations."""

    def test_read_secret_file(self, tmp_path):
        """Test reading secret from file."""
        secret_file = tmp_path / "secret.txt"
        secret = "my-secret"
        secret_file.write_text(secret)
        
        assert SessionManager._read_secret_file(str(secret_file)) == secret

    def test_read_secret_file_not_found(self):
        """Test reading from non-existent file returns placeholder."""
        result = SessionManager._read_secret_file("/nonexistent/file.txt")
        assert result == PLACEHOLDER_SECRET

    def test_generate_secret(self):
        """Test generating a new secret."""
        secret = SessionManager.generate_secret()
        assert isinstance(secret, str)
        assert len(secret) > 64

    def test_write_secret_file(self, tmp_path):
        """Test writing secret to file."""
        secret_file = tmp_path / "secret.txt"
        secret = "my-secret"
        
        result = SessionManager.write_secret_file(str(secret_file), secret)
        assert result == secret
        assert secret_file.read_text() == secret

    def test_write_secret_file_generates(self, tmp_path):
        """Test writing secret to file generates new secret if not provided."""
        secret_file = tmp_path / "secret.txt"
        
        result = SessionManager.write_secret_file(str(secret_file))
        assert isinstance(result, str)
        assert len(result) > 64
        assert secret_file.read_text() == result


class TestSessionManagerCreate:
    """Test session creation."""

    def test_create_session(self):
        """Test creating a session token."""
        manager = SessionManager(secret="test-secret")
        token = manager.create_session(123)
        
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_session_different_users(self):
        """Test that different users produce different tokens."""
        manager = SessionManager(secret="test-secret")
        token1 = manager.create_session(1)
        token2 = manager.create_session(2)
        
        assert token1 != token2


class TestSessionManagerValidate:
    """Test session validation."""

    def test_validate_session(self):
        """Test validating a valid session token."""
        manager = SessionManager(secret="test-secret")
        token = manager.create_session(123)
        
        payload = manager.validate_session(token)
        assert payload["user_id"] == 123
        assert "iat" in payload

    def test_validate_session_invalid_signature(self):
        """Test validating session with invalid signature."""
        manager = SessionManager(secret="test-secret")
        
        with pytest.raises(Exception):  # BadSignature
            manager.validate_session("invalid-token")

    def test_validate_session_expired(self):
        """Test validating expired session."""
        manager = SessionManager(secret="test-secret", ttl=1)  # 1 second TTL
        token = manager.create_session(123)
        
        time.sleep(2)  # Wait for token to expire
        
        with pytest.raises(Exception):  # SignatureExpired
            manager.validate_session(token)


class TestSessionManagerRenewal:
    """Test session renewal."""

    def test_needs_renewal_true(self):
        """Test that old sessions need renewal."""
        manager = SessionManager(secret="test-secret", ttl=3600)
        
        # Create payload with old timestamp
        payload = {"user_id": 123, "iat": int(time.time()) - 3601}
        
        assert manager.needs_renewal(payload) is True

    def test_needs_renewal_false(self):
        """Test that recent sessions do not need renewal."""
        manager = SessionManager(secret="test-secret", ttl=3600)
        
        # Create payload with recent timestamp
        payload = {"user_id": 123, "iat": int(time.time())}
        
        assert manager.needs_renewal(payload) is False

    def test_renew_session(self):
        """Test renewing a session token."""
        manager = SessionManager(secret="test-secret")
        token = manager.create_session(123)
        
        # Wait a bit
        time.sleep(0.1)
        
        # Renew
        new_token = manager.renew_session(token)
        
        assert new_token != token
        payload = manager.validate_session(new_token)
        assert payload["user_id"] == 123


class TestGetSessionManager:
    """Test get_session_manager function."""

    def test_get_session_manager_singleton(self):
        """Test that get_session_manager returns the same instance."""
        # Reset global state
        import audio_to_subs.auth.sessions as sessions_module
        sessions_module._session_manager = None
        
        manager1 = get_session_manager()
        manager2 = get_session_manager()
        
        assert manager1 is manager2

    def test_get_session_manager_creates(self):
        """Test that get_session_manager creates a manager."""
        import audio_to_subs.auth.sessions as sessions_module
        sessions_module._session_manager = None
        
        manager = get_session_manager()
        assert isinstance(manager, SessionManager)
