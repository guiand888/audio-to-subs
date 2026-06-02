"""FastAPI dependencies for the API."""

from typing import Annotated, Any

from fastapi import Depends

from audio_to_subs.api.settings import get_settings, Settings
from audio_to_subs.auth.deps import get_current_user, get_db, get_optional_user
from audio_to_subs.db.models import User


def get_settings_dep() -> Settings:
    """FastAPI dependency for settings."""
    return get_settings()


# Re-export from auth.deps for convenience
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
DatabaseSession = Annotated[Any, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
