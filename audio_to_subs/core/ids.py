"""Short, unique, dependency-free identifier generation for jobs.

Job IDs used to be 36-char UUIDs. They are unique but verbose for a UI where
the ID is shown to users and linked between pages. We keep the uniqueness
guarantee with a compact base62 string instead.

12 base62 chars (62^12 ≈ 2^71) give collision-negligible entropy at the scale
this app operates at, while being short enough to display and copy.
"""

import secrets

# base62 alphabet: 0-9, A-Z, a-z. Avoids ambiguous chars on purpose? We keep
# the full set for max entropy per character; I/O is copy/paste, not manual.
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

JOB_ID_LENGTH = 12


def generate_job_id() -> str:
    """Return a new random 12-char base62 job ID.

    Uses ``secrets`` (cryptographically strong) rather than ``random`` so IDs
    are unpredictable as well as unique.
    """
    return "".join(secrets.choice(_ALPHABET) for _ in range(JOB_ID_LENGTH))
