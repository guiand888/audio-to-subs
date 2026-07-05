"""Settings API routes."""

import json
import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from audio_to_subs.api.deps import SettingsDep, get_db

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# Default settings values
DEFAULT_SETTINGS = {
    "mistral_model": "voxtral-mini-latest",
    "mistral_rate_usd_per_minute": 0.003,
    "mistral_input_token_rate_usd": None,
    "mistral_output_token_rate_usd": None,
    "bazarr_poll_interval": 3600,
    "bazarr_track_no_subs": False,
    "bazarr_url": None,
    "bazarr_api_key": None,
    "bazarr_timeout": 30.0,
    "path_mappings": [],
    "default_language": "en",
    "default_output_format": "srt",
    "movies_root_path": "/movies",
    "tv_root_path": "/tv",
    "subtitles_same_directory": True,
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
    bazarr_url: str | None = Field(
        default=None, description="Bazarr API base URL"
    )
    bazarr_api_key: str | None = Field(
        default=None, description="Bazarr API key"
    )
    bazarr_timeout: float = Field(
        default=30.0, description="Bazarr API timeout in seconds"
    )
    path_mappings: list[dict[str, str]] = Field(
        default_factory=list, description="List of path mapping dicts"
    )
    default_language: str = Field(description="Default language code")
    default_output_format: str = Field(description="Default output format")
    movies_root_path: str | None = Field(
        default="/movies", description="Root path for movie files"
    )
    tv_root_path: str | None = Field(
        default="/tv", description="Root path for TV series files"
    )
    subtitles_same_directory: bool = Field(
        default=True, description="Save subtitles alongside source video files"
    )

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
    bazarr_url: str | None = Field(
        default=None, description="Bazarr API base URL"
    )
    bazarr_api_key: str | None = Field(
        default=None, description="Bazarr API key"
    )
    bazarr_timeout: float | None = Field(
        default=None, description="Bazarr API timeout in seconds"
    )
    path_mappings: list[dict[str, str]] | None = Field(
        default=None, description="List of path mapping dicts"
    )
    default_language: str | None = Field(default=None, description="Default language code")
    default_output_format: str | None = Field(
        default=None, description="Default output format"
    )
    movies_root_path: str | None = Field(
        default=None, description="Root path for movie files"
    )
    tv_root_path: str | None = Field(
        default=None, description="Root path for TV series files"
    )
    subtitles_same_directory: bool | None = Field(
        default=None, description="Save subtitles alongside source video files"
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
    existing_count = len(result.scalars().all())

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

    # Update or insert each setting (all changes in one transaction for atomicity)
    for key, value in updates.items():
        # Check if setting exists
        result = await db.execute(
            select(Setting).where(Setting.key == key)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.value_json = json.dumps(value)
            await db.flush()  # Ensure update is queued before next check
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


# Connection test models
class BazarrConnectionTestRequest(BaseModel):
    """Optional overrides for the Bazarr connection test.

    When bazarr_url is provided, the test targets these values directly
    instead of the saved DB/env settings - this lets the Settings page test
    unsaved, currently-edited form values before the user clicks Save.
    """

    bazarr_url: str | None = Field(
        default=None, description="Bazarr URL to test (overrides saved settings)"
    )
    bazarr_api_key: str | None = Field(
        default=None, description="Bazarr API key to test (overrides saved settings)"
    )
    bazarr_timeout: float | None = Field(
        default=None, description="Bazarr timeout to test (overrides saved settings)"
    )


class BazarrConnectionTestResponse(BaseModel):
    """Response for Bazarr connection test."""

    success: bool = Field(description="Whether the connection test succeeded")
    message: str | None = Field(
        default=None, description="Success message or detailed error description"
    )
    error: str | None = Field(default=None, description="Error type or category")


@router.post(
    "/test-bazarr-connection",
    response_model=BazarrConnectionTestResponse,
    status_code=status.HTTP_200_OK,
)
async def test_bazarr_connection(
    db: Annotated["AsyncSession", Depends(get_db)],
    settings: SettingsDep,
    test_request: BazarrConnectionTestRequest = Body(
        default_factory=BazarrConnectionTestRequest
    ),
) -> BazarrConnectionTestResponse:
    """Test connectivity to Bazarr API.

    Attempts to connect to Bazarr and verifies the connection is working. If
    bazarr_url is provided in the request body, tests those (possibly unsaved)
    values directly; otherwise uses configured settings (database first, then
    environment variables).

    This endpoint:
    - Tests request-body overrides if provided, else DB settings, else env vars
    - Makes a lightweight API call to test connectivity
    - NEVER exposes API keys, URLs, or other sensitive data in responses or logs
    - Returns success/failure with user-friendly messages

    Returns:
        Connection test result with success status and message
    """
    from audio_to_subs.bazarr.poller import get_bazarr_client, get_bazarr_client_with_settings

    try:
        if test_request.bazarr_url is not None:
            # Test the values currently in the (possibly unsaved) settings form.
            client = await get_bazarr_client(
                test_request.bazarr_url,
                test_request.bazarr_api_key,
                test_request.bazarr_timeout
                if test_request.bazarr_timeout is not None
                else 30.0,
            )
        else:
            # Get Bazarr client using database settings first, then environment fallback
            client, bazarr_url, bazarr_api_key, bazarr_timeout = await get_bazarr_client_with_settings(
                db, settings
            )

        if client is None:
            return BazarrConnectionTestResponse(
                success=False,
                message=None,
                error="bazarr_not_configured",
            )

        # Attempt a lightweight API call to test connectivity
        # Use list_all_series with limit=1 to minimize impact
        try:
            series_page = await client.list_all_series(start=0, length=1)
            # If we get here, the connection succeeded
            await client.close()
            return BazarrConnectionTestResponse(
                success=True,
                message="Connected to Bazarr successfully",
                error=None,
            )

        except Exception as e:
            # Handle various error types - never expose sensitive data
            await client.close()
            error_type = type(e).__name__

            # Map error types to user-friendly messages
            if error_type == "BazarrAuthError":
                return BazarrConnectionTestResponse(
                    success=False,
                    message=None,
                    error="authentication_failed",
                )
            elif error_type == "BazarrNotFoundError":
                return BazarrConnectionTestResponse(
                    success=False,
                    message=None,
                    error="resource_not_found",
                )
            elif error_type == "BazarrRateLimited":
                return BazarrConnectionTestResponse(
                    success=False,
                    message=None,
                    error="rate_limited",
                )
            elif error_type == "BazarrServerError":
                return BazarrConnectionTestResponse(
                    success=False,
                    message=None,
                    error="server_error",
                )
            else:
                # Generic error - log it but don't expose details to user
                logger.warning("Bazarr connection test failed: %s", error_type)
                return BazarrConnectionTestResponse(
                    success=False,
                    message=None,
                    error="connection_failed",
                )

    except Exception as e:
        # Catch any unexpected errors during client creation
        logger.error("Unexpected error during Bazarr connection test: %s", type(e).__name__)
        return BazarrConnectionTestResponse(
            success=False,
            message=None,
            error="internal_error",
        )
