"""Tests for password hashing."""

import pytest

from audio_to_subs.auth.passwords import (
    hash_password,
    needs_rehash,
    verify_password,
)


class TestHashPassword:
    """Test password hashing."""

    def test_hash_password_returns_string(self):
        """Test that hash_password returns a string."""
        hashed = hash_password("password123")
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_password_different_for_different_inputs(self):
        """Test that different passwords produce different hashes."""
        hashed1 = hash_password("password1")
        hashed2 = hash_password("password2")
        assert hashed1 != hashed2

    def test_hash_password_same_for_same_input(self):
        """Test that same password produces same hash (deterministic)."""
        # Note: This is not guaranteed with argon2 due to salt
        # Each hash will be different even for same input
        hashed1 = hash_password("password123")
        hashed2 = hash_password("password123")
        # They should be different due to random salt
        assert hashed1 != hashed2


class TestVerifyPassword:
    """Test password verification."""

    def test_verify_password_correct(self):
        """Test that correct password verifies."""
        hashed = hash_password("password123")
        assert verify_password("password123", hashed) is True

    def test_verify_password_incorrect(self):
        """Test that incorrect password does not verify."""
        hashed = hash_password("password123")
        assert verify_password("wrongpassword", hashed) is False

    def test_verify_password_empty_hash(self):
        """Test verification with empty hash."""
        assert verify_password("password", "") is False

    def test_verify_password_invalid_hash(self):
        """Test verification with invalid hash."""
        assert verify_password("password", "invalid-hash-string") is False


class TestNeedsRehash:
    """Test rehash detection."""

    def test_needs_rehash_with_valid_hash(self):
        """Test rehash detection with valid hash."""
        hashed = hash_password("password123")
        # Should not need rehash if parameters match
        assert needs_rehash(hashed) is False

    def test_needs_rehash_with_invalid_hash(self):
        """Test rehash detection with invalid hash."""
        assert needs_rehash("invalid-hash") is False
