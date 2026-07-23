"""Settings API routes."""

import json
import logging
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select

from audio_to_subs.api.deps import SettingsDep, get_db

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# Sentinel returned in place of secrets (bazarr_api_key) in API responses.
# Never valid as a real credential - any endpoint receiving this value back
# must treat it as "unchanged", not forward it to Bazarr or persist it.
MASKED_VALUE = "***MASKED***"

# Fixed timeout for the "Test Connection" probe (test_bazarr_connection),
# deliberately independent of the user-configurable bazarr_timeout setting
# (which governs real sync/poll requests and defaults to 30s). A connection
# test should fail fast and give the user quick feedback, not hang for as
# long as production requests are allowed to.
CONNECTION_TEST_TIMEOUT_SECONDS = 5.0


# Default settings values
DEFAULT_SETTINGS = {
    "mistral_model": "voxtral-mini-2602",
    "mistral_rate_usd_per_minute": 0.003,
    "mistral_input_token_rate_usd": None,
    "mistral_output_token_rate_usd": None,
    "bazarr_poll_interval": 3600,
    "bazarr_url": None,
    "bazarr_api_key": None,
    "bazarr_timeout": 30.0,
    "path_mappings": [],
    "default_language": "en",
    "default_output_format": "srt",
    "subtitles_same_directory": True,
    "max_audio_length": 900,
    "timezone": "UTC",
}


# Response models
class SettingsResponse(BaseModel):
    """Full settings response."""

    mistral_model: str = Field(description="Mistral model to use")
    mistral_rate_usd_per_minute: float = Field(
        description="Primary audio duration billing rate (USD per minute)"
    )
    mistral_input_token_rate_usd: float | None = Field(
        default=None,
        description="Optional token-based input billing rate (USD per token)",
    )
    mistral_output_token_rate_usd: float | None = Field(
        default=None,
        description="Optional token-based output billing rate (USD per token)",
    )
    bazarr_poll_interval: int = Field(description="Bazarr poll interval in seconds")
    bazarr_url: str | None = Field(default=None, description="Bazarr API base URL")
    bazarr_api_key: str | None = Field(default=None, description="Bazarr API key")
    bazarr_timeout: float = Field(
        default=30.0, description="Bazarr API timeout in seconds"
    )
    path_mappings: list[dict[str, str]] = Field(
        default_factory=list, description="List of path mapping dicts"
    )
    default_language: str = Field(description="Default language code")
    default_output_format: str = Field(description="Default output format")
    subtitles_same_directory: bool = Field(
        default=True, description="Save subtitles alongside source video files"
    )
    max_audio_length: int = Field(
        default=900, description="Maximum audio segment length in seconds (60-10800)"
    )
    timezone: str = Field(
        default="UTC",
        description="IANA timezone (e.g. 'Europe/Paris') for UI time display",
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

    def sanitized(self) -> "SettingsResponse":
        """Return a copy with sensitive fields masked for API responses.

        bazarr_api_key is intentionally write-only once set: it is never
        returned in cleartext by any endpoint (GET, PATCH, or GET /{key}),
        so anyone with UI/API access after the fact - not just at save time -
        cannot exfiltrate it. There is no "reveal saved key" endpoint and
        none should be added without deliberate security sign-off; the
        frontend reveal toggle only shows what's currently typed, not the
        saved value.
        """
        copy = self.model_copy()
        # Mask API keys - return only if they were not set
        if copy.bazarr_api_key:
            copy.bazarr_api_key = MASKED_VALUE
        return copy


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
    bazarr_url: str | None = Field(default=None, description="Bazarr API base URL")
    bazarr_api_key: str | None = Field(default=None, description="Bazarr API key")
    bazarr_timeout: float | None = Field(
        default=None, description="Bazarr API timeout in seconds"
    )
    path_mappings: list[dict[str, str]] | None = Field(
        default=None, description="List of path mapping dicts"
    )
    default_language: str | None = Field(
        default=None, description="Default language code"
    )
    default_output_format: str | None = Field(
        default=None, description="Default output format"
    )
    subtitles_same_directory: bool | None = Field(
        default=None, description="Save subtitles alongside source video files"
    )
    max_audio_length: int | None = Field(
        default=None, description="Maximum audio segment length in seconds (60-10800)"
    )
    timezone: str | None = Field(
        default=None,
        description="IANA timezone (e.g. 'Europe/Paris') for UI time display",
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        """Validate timezone is a real IANA zone (per security: never trust input)."""
        if v is None:
            return v
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"Invalid IANA timezone: {v}") from e
        return v

    @field_validator("max_audio_length")
    @classmethod
    def validate_max_audio_length(cls, v: int | None) -> int | None:
        """Validate max_audio_length is within bounds (60-10800)."""
        if v is None:
            return v
        from audio_to_subs.core.models import MAX_AUDIO_LENGTH_BOUNDS

        lo, hi = MAX_AUDIO_LENGTH_BOUNDS
        if not (lo <= v <= hi):
            raise ValueError(f"max_audio_length must be between {lo} and {hi} seconds")
        return v

    @field_validator("bazarr_url")
    @classmethod
    def validate_bazarr_url(cls, v: str | None) -> str | None:
        """Validate bazarr_url is a valid HTTP(S) URL (SSRF prevention)."""
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError("bazarr_url must be a string")
        # Ensure it's http or https and has a valid format
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("bazarr_url must start with http:// or https://")
        try:
            from urllib.parse import urlparse

            parsed = urlparse(v)
            if not parsed.netloc:
                raise ValueError("bazarr_url must have a valid hostname")
        except Exception as e:
            raise ValueError(f"Invalid bazarr_url format: {e}") from e
        return v


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
) -> bool:
    """Seed default settings unconditionally.

    Caller is responsible for checking whether the table is already
    populated (see ``get_settings``) - this avoids a redundant COUNT query.

    Returns:
        True once settings have been seeded.
    """
    from audio_to_subs.db.models import Setting

    for key, value in DEFAULT_SETTINGS.items():
        setting = Setting(
            key=key,
            value_json=json.dumps(value),
        )
        db.add(setting)
    await db.commit()
    logger.info("Seeded %d default settings", len(DEFAULT_SETTINGS))
    return True


@router.get("", response_model=SettingsResponse)
async def get_settings(
    db: Annotated["AsyncSession", Depends(get_db)],
) -> SettingsResponse:
    """Get all application settings.

    Returns current settings from the database, merged with defaults.
    """
    from audio_to_subs.db.models import Setting

    # Only seed defaults if the table is empty (first boot)
    result = await db.execute(select(func.count(Setting.key)))
    if (result.scalar() or 0) == 0:
        await _seed_default_settings(db)

    # Get all settings
    db_settings = await _get_all_settings(db)

    response = SettingsResponse.from_db_settings(db_settings)
    return response.sanitized()


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

    # The sentinel is only ever a display placeholder for an already-saved
    # key (see SettingsResponse.sanitized()) - never a real credential. A
    # client that echoes a GET response back unedited must not clobber the
    # saved key with it.
    if updates.get("bazarr_api_key") == MASKED_VALUE:
        del updates["bazarr_api_key"]

    merged_settings = {**current_settings, **updates}

    # Fetch all existing settings for the keys being updated (single query)
    keys_to_update = list(updates.keys())
    if keys_to_update:
        result = await db.execute(
            select(Setting).where(Setting.key.in_(keys_to_update))
        )
        existing_settings = {s.key: s for s in result.scalars().all()}
    else:
        existing_settings = {}

    # Update or insert each setting (all changes in one transaction for atomicity)
    for key, value in updates.items():
        existing = existing_settings.get(key)

        if existing:
            existing.value_json = json.dumps(value)
        else:
            new_setting = Setting(
                key=key,
                value_json=json.dumps(value),
            )
            db.add(new_setting)

    await db.commit()

    # Return full settings with secrets masked
    response = SettingsResponse.from_db_settings(merged_settings)
    return response.sanitized()


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

    result = await db.execute(select(Setting.value_json).where(Setting.key == key))
    row = result.scalar_one_or_none()

    if row is None:
        # Check if it's a default setting
        if key in DEFAULT_SETTINGS:
            value = DEFAULT_SETTINGS[key]
            # Mask sensitive settings (only if actually set - don't mask a null/empty value)
            if value and key in ("bazarr_api_key", "SESSION_SECRET"):
                value = MASKED_VALUE
            return {"key": key, "value": value}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting {key} not found",
        )

    try:
        value = json.loads(row)
        # Mask sensitive settings (only if actually set - don't mask a null/empty value)
        if value and key in ("bazarr_api_key", "SESSION_SECRET"):
            value = MASKED_VALUE
        return {"key": key, "value": value}
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse setting {key}",
        ) from e


# Connection test models
class BazarrConnectionTestRequest(BaseModel):
    """Optional overrides for the Bazarr connection test.

    When bazarr_url is provided, the test targets these values directly
    instead of the saved DB/env settings - this lets the Settings page test
    unsaved, currently-edited form values before the user clicks Save.

    Deliberately has no bazarr_timeout field: the test always uses
    CONNECTION_TEST_TIMEOUT_SECONDS, not the user-configured production
    timeout (see that constant's docstring for why).
    """

    bazarr_url: str | None = Field(
        default=None, description="Bazarr URL to test (overrides saved settings)"
    )
    bazarr_api_key: str | None = Field(
        default=None, description="Bazarr API key to test (overrides saved settings)"
    )


class BazarrConnectionTestResponse(BaseModel):
    """Response for Bazarr connection test."""

    success: bool = Field(description="Whether the connection test succeeded")
    message: str | None = Field(
        default=None, description="Success message or detailed error description"
    )
    error: (
        Literal[
            "bazarr_not_configured",
            "authentication_failed",
            "resource_not_found",
            "rate_limited",
            "server_error",
            "unexpected_response",
            "connection_failed",
            "internal_error",
        ]
        | None
    ) = Field(default=None, description="Error type or category")


def _map_bazarr_test_error(
    e: Exception,
) -> Literal[
    "authentication_failed",
    "resource_not_found",
    "rate_limited",
    "server_error",
    "unexpected_response",
    "connection_failed",
]:
    """Map a Bazarr connection-test exception to a user-facing error code.

    Logs details for the categories that warrant it; never exposes
    credentials, URLs, or other sensitive data to the client.
    """
    from audio_to_subs.bazarr.client import (
        BazarrAuthError,
        BazarrNotFoundError,
        BazarrRateLimited,
        BazarrServerError,
    )

    if isinstance(e, BazarrAuthError):
        return "authentication_failed"
    elif isinstance(e, BazarrNotFoundError):
        return "resource_not_found"
    elif isinstance(e, BazarrRateLimited):
        return "rate_limited"
    elif isinstance(e, BazarrServerError):
        return "server_error"
    elif isinstance(e, ValidationError):
        # Reached Bazarr and got a response, but it didn't match our
        # schema - this is schema drift, not a connectivity problem.
        # Log field locations only, never payload values (may contain
        # user media paths/titles).
        locs = sorted({".".join(str(p) for p in err["loc"]) for err in e.errors()})
        logger.warning(
            "Bazarr connection test: unexpected response shape "
            "(%d validation error(s) at: %s)",
            e.error_count(),
            ", ".join(locs),
        )
        return "unexpected_response"
    else:
        # Generic error - log it but don't expose details to user
        logger.warning("Bazarr connection test failed: %s", type(e).__name__)
        return "connection_failed"


@router.post(
    "/test-bazarr-connection",
    response_model=BazarrConnectionTestResponse,
    status_code=status.HTTP_200_OK,
)
async def test_bazarr_connection(
    db: Annotated["AsyncSession", Depends(get_db)],
    settings: SettingsDep,
    test_request: BazarrConnectionTestRequest = Body(  # noqa: B008
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
    - Always uses CONNECTION_TEST_TIMEOUT_SECONDS, regardless of the
      configured/overridden bazarr_timeout (see that constant's docstring)
    - NEVER exposes API keys, URLs, or other sensitive data in responses or logs
    - Returns success/failure with user-friendly messages

    Returns:
        Connection test result with success status and message
    """
    from audio_to_subs.bazarr.poller import (
        get_bazarr_client,
        get_bazarr_client_with_settings,
    )

    try:
        bazarr_url: str | None
        api_key: str | None
        if test_request.bazarr_url is not None:
            # Test the values currently in the (possibly unsaved) settings form.
            bazarr_url = test_request.bazarr_url
            api_key = test_request.bazarr_api_key
            if api_key is None or api_key == MASKED_VALUE:
                # The API key field is blank or still holds the masked
                # placeholder from a prior GET (the raw key is never sent to
                # the client) - fall back to the saved key rather than using
                # the placeholder as a literal credential.
                _, _, api_key, _ = await get_bazarr_client_with_settings(db, settings)
        else:
            # Use configured settings (database first, then environment
            # fallback). The client/timeout this returns are discarded below -
            # the test always builds its own client with the fixed test
            # timeout instead of whatever bazarr_timeout is configured.
            _, bazarr_url, api_key, _ = await get_bazarr_client_with_settings(
                db, settings
            )

        client = await get_bazarr_client(
            bazarr_url, api_key, CONNECTION_TEST_TIMEOUT_SECONDS
        )

        if client is None:
            return BazarrConnectionTestResponse(
                success=False,
                message=None,
                error="bazarr_not_configured",
            )

        # Attempt a lightweight, auth-checked API call to test connectivity.
        # list_all_series(length=1) is the best available probe in Bazarr's
        # API (verified against Bazarr's own source, not just its docs):
        #   - /api/system/ping is explicitly unauthenticated and always
        #     returns 200, so it would report "success" even with a wrong
        #     or missing API key - useless for an auth test.
        #   - /api/system/status looks lighter but calls into
        #     get_radarr_info.version()/get_sonarr_info.version(), which make
        #     live outbound HTTP requests to the user's Radarr/Sonarr
        #     instances (only cached for 60s) - slower and adds failure modes
        #     unrelated to Bazarr itself.
        #   - /api/badges runs several DB aggregate queries across episodes,
        #     movies, health and providers - not actually cheaper.
        # /api/series requires the same @authenticate check as every other
        # endpoint and, with length=1, returns at most one row.
        try:
            await client.list_all_series(start=0, length=1)
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
            return BazarrConnectionTestResponse(
                success=False,
                message=None,
                error=_map_bazarr_test_error(e),
            )

    except Exception as e:
        # Catch any unexpected errors during client creation
        logger.error(
            "Unexpected error during Bazarr connection test: %s", type(e).__name__
        )
        return BazarrConnectionTestResponse(
            success=False,
            message=None,
            error="internal_error",
        )
