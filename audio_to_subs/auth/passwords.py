"""Password hashing using argon2."""

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError

# Password hasher with safe defaults
# argon2id, m=64 MiB, t=3, p=1
_PH = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
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
        True if hash should be upgraded, False otherwise
    """
    # check_needs_rehash returns a bool for valid hashes.  For invalid or
    # malformed strings it raises InvalidHashError; treat that as "no rehash
    # needed" rather than propagating.
    try:
        return _PH.check_needs_rehash(hashed)
    except Exception:
        return False
