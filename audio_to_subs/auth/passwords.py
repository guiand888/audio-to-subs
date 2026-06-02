"""Password hashing using argon2."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Password hasher with safe defaults
# id = argon2id, m=64 MiB, t=3, p=1
_PH = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=2,  # argon2id
)


def hash_password(plain: str) -> str:
    """Hash a password using argon2id.
    
    Args:
        plain: Plain text password
    
    Returns:
        Argon2 hashed password string
    """
    return _PH.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against an argon2 hash.
    
    Args:
        plain: Plain text password to verify
        hashed: Stored argon2 hash
    
    Returns:
        True if password matches, False otherwise
    """
    try:
        _PH.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        # Invalid hash format or other error
        return False


def needs_rehash(hashed: str) -> bool:
    """Check if a password hash needs to be rehashed with current parameters.
    
    Args:
        hashed: Stored argon2 hash
    
    Returns:
        True if hash should be upgraded
    """
    try:
        _PH.check_needs_rehash(hashed)
        return True
    except Exception:
        return False
