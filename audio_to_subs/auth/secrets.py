"""Placeholder-secret refusal.

Ensures the application refuses to start when configured with well-known
default/placeholder secret values, so a misconfigured deployment never runs
with credentials that are public knowledge. See M6.a security pass.
"""

from typing import TYPE_CHECKING

from audio_to_subs.auth.sessions import PLACEHOLDER_SECRET

if TYPE_CHECKING:
    from audio_to_subs.api.settings import Settings

# (human label, Settings property, placeholder value) tuples.
_PLACEHOLDER_SECRETS: tuple[tuple[str, str, str], ...] = (
    ("SESSION_SECRET", "session_secret", PLACEHOLDER_SECRET),
    ("MISTRAL_API_KEY", "mistral_api_key", "your_api_key_here"),
    ("ADMIN_PASSWORD", "admin_password", "changeme"),
)


def refuse_placeholder_secrets(settings: "Settings") -> None:
    """Raise if any secret is still a known placeholder value.

    Args:
        settings: The application ``Settings`` instance.

    Raises:
        RuntimeError: If a secret equals its placeholder default. The SESSION_SECRET
            placeholder ("changeme") is also enforced deep inside ``SessionManager``,
            but this central check fails fast at startup before any work begins.
    """
    for label, attr, placeholder in _PLACEHOLDER_SECRETS:
        value = getattr(settings, attr, None)
        if value is not None and value == placeholder:
            raise RuntimeError(
                f"Refusing to start: {label} is set to the default placeholder "
                f"value ({placeholder!r}). Configure a real secret before starting."
            )
