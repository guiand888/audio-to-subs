"""Settings API routes."""

import json
import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from audio_to_subs.api.deps import get_db

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# Default settings values
DEFAULT_SETTINGS = {
    "mistral_model": "mistral-medium-latest",
    "mistral_rate_usd_per_minute": 0.0,
    "mistral_input_token_rate_usd": None,
    "mistral_output_token_rate_usd": None,
    "bazarr_poll_interval": 3600,
    "bazarr_track_no_subs": False,
    "path_mappings": [],
    "default_language": "en",
    "default_output_format": "srt",
}


# Response models
class SettingsResponse(BaseModel):
    """Full settings response."""

    mistral_model: str = Field(description="Mistral model to use")
    mistral_rate_usd_per_minute: float = Field(
        description="Primary audio duration billing rate (USD per minute)"
    )
    mistral_input_token_rate_usd: float | None = Field(
        default=None, description="Optional token-based input billing rate (USD per token)"
    )
    mistral_output_token_rate_usd: float | None = Field(
        default=None, description="Optional token-based output billing rate (USD per token)"
    )
    bazarr_poll_interval: int = Field(
        description="Bazarr poll interval in seconds"
    )
    bazarr_track_no_subs: bool = Field(
        description="Track items with no subtitles in any language"
    )
    path_mappings: list[dict[str, str]] = Field(
        default_factory=list, description="List of path mapping dicts"
    )
    default_language: str = Field(description="Default language code")
    default_output_format: str = Field(description="Default output format")

    @classmethod
    def from_db_settings(cls, db_settings: dict[str, Any]) -> "SettingsResponse":
        """Create SettingsResponse from database settings dict."""
        # Merge with defaults
        settings = {**DEFAULT_SETTINGS, **db_settings}
        return cls.model_validate(settings)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return self.model_dump()


class SettingsUpdate(BaseModel):
    """Settings update request (all fields optional)."""

    mistral_model: str | None = Field(default=None, description="Mistral model to use")
    mistral_rate_usd_per_minute: float | None = Field(
        default=None, description="Primary audio duration billing rate"
    )
    mistral_input_token_rate_usd: float | None = Field(
        default=None, description="Optional token-based input billing rate"
    )
    mistral_output_token_rate_usd: float | None = Field(
        default=None, description="Optional token-based output billing rate"
    )
    bazarr_poll_interval: int | None = Field(
        default=None, description="Bazarr poll interval in seconds"
    )
    bazarr_track_no_subs: bool | None = Field(
        default=None, description="Track items with no subtitles in any language"
    )
    path_mappings: list[dict[str, str]] | None = Field(
        default=None, description="List of path mapping dicts"
    )
    default_language: str | None = Field(default=None, description="Default language code")
    default_output_format: str | None = Field(
        default=None, description="Default output format"
    )


async def _get_all_settings(
    db: Annotated["AsyncSession", Depends(get_db)],
) -> dict[str, Any]:
    """Get all settings from the database."""
    from audio_to_subs.db.models import Setting

    result = await db.execute(select(Setting))
    settings_rows = result.scalars().all()

    settings: dict[str, Any] = {}
    for row in settings_rows:
        try:
            value = json.loads(row.value_json)
            settings[row.key] = value
        except json.JSONDecodeError:
            logger.warning("Failed to parse setting %s: %s", row.key, row.value_json)

    return settings


async def _seed_default_settings(
    db: Annotated["AsyncSession", Depends(get_db)],
) -> None:
    """Seed default settings if not present."""
    from audio_to_subs.db.models import Setting

    result = await db.execute(select(Setting))
    existing_count = result.rowcount

    if existing_count == 0:
        for key, value in DEFAULT_SETTINGS.items():
            setting = Setting(
                key=key,
                value_json=json.dumps(value),
            )
            db.add(setting)
        await db.commit()
        logger.info("Seeded %d default settings", len(DEFAULT_SETTINGS))


@router.get("", response_model=SettingsResponse)
async def get_settings(
    db: Annotated["AsyncSession", Depends(get_db)],
) -> SettingsResponse:
    """Get all application settings.

    Returns current settings from the database, merged with defaults.
    """
    # Seed defaults if needed
    await _seed_default_settings(db)

    # Get all settings
    db_settings = await _get_all_settings(db)

    return SettingsResponse.from_db_settings(db_settings)


@router.patch("", response_model=SettingsResponse, status_code=status.HTTP_200_OK)
async def update_settings(
    db: Annotated["AsyncSession", Depends(get_db)],
    settings_update: SettingsUpdate,
) -> SettingsResponse:
    """Update application settings.

    Merges provided values with existing settings. Does not replace missing fields.
    """
    from audio_to_subs.db.models import Setting

    # Get current settings
    current_settings = await _get_all_settings(db)

    # Merge updates
    updates = settings_update.model_dump(exclude_unset=True)
    merged_settings = {**current_settings, **updates}

    # Update or insert each setting
    for key, value in updates.items():
        # Check if setting exists
        result = await db.execute(
            select(Setting).where(Setting.key == key)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.value_json = json.dumps(value)
        else:
            new_setting = Setting(
                key=key,
                value_json=json.dumps(value),
            )
            db.add(new_setting)

    await db.commit()

    # Return full settings
    return SettingsResponse.from_db_settings(merged_settings)


@router.get("/{key}")
async def get_setting(
    key: str,
    db: Annotated["AsyncSession", Depends(get_db)],
) -> dict[str, Any]:
    """Get a specific setting by key.

    Args:
        key: Setting key

    Returns:
        Setting value as JSON
    """
    from audio_to_subs.db.models import Setting

    result = await db.execute(
        select(Setting.value_json).where(Setting.key == key)
    )
    row = result.scalar_one_or_none()

    if row is None:
        # Check if it's a default setting
        if key in DEFAULT_SETTINGS:
            return {"key": key, "value": DEFAULT_SETTINGS[key]}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting {key} not found",
        )

    try:
        value = json.loads(row.value_json)
        return {"key": key, "value": value}
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse setting {key}",
        )
