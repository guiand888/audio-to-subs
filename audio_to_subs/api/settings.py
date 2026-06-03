"""Application settings using pydantic-settings."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # Database
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:////data/audio-to-subs.db",
        description="Database connection URL",
    )

    # Session
    SESSION_SECRET: str | None = Field(
        default=None,
        description="Session secret key",
    )
    SESSION_SECRET_FILE: str | None = Field(
        default=None,
        description="Path to file containing session secret",
    )

    # Admin credentials
    ADMIN_USERNAME: str | None = Field(
        default=None,
        description="Admin username for bootstrap",
    )
    ADMIN_PASSWORD: str | None = Field(
        default=None,
        description="Admin password for bootstrap",
    )
    ADMIN_PASSWORD_FILE: str | None = Field(
        default=None,
        description="Path to file containing admin password",
    )

    # Security
    BEHIND_TLS: bool = Field(
        default=False,
        description="Set Secure flag on cookies when behind TLS",
    )

    # Redis
    REDIS_URL: str = Field(
        default="redis://redis:6379/0",
        description="Redis connection URL",
    )

    # Bazarr
    BAZARR_URL: str | None = Field(
        default=None,
        description="Bazarr API URL",
    )
    BAZARR_API_KEY: str | None = Field(
        default=None,
        description="Bazarr API key",
    )

    # Mistral
    MISTRAL_API_KEY: str | None = Field(
        default=None,
        description="Mistral API key",
    )
    MISTRAL_API_KEY_FILE: str | None = Field(
        default=None,
        description="Path to file containing Mistral API key",
    )

    # Application
    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode",
    )

    # Media paths
    MOVIES_ROOT_PATH: str | None = Field(
        default="/movies",
        description="Root path for movie files (Sonarr/Radarr aligned)",
    )
    TV_ROOT_PATH: str | None = Field(
        default="/tv",
        description="Root path for TV series files (Sonarr/Radarr aligned)",
    )
    SUBTITLES_SAME_DIRECTORY: bool = Field(
        default=True,
        description="Save subtitles in same directory as source video files",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("ADMIN_PASSWORD", mode="before")
    @classmethod
    def load_admin_password_from_file(
        cls, v: str | None, values: dict[str, Any]
    ) -> str | None:
        """Load admin password from file if ADMIN_PASSWORD_FILE is set."""
        if v is not None:
            return v
        
        password_file = values.get("ADMIN_PASSWORD_FILE")
        if password_file is not None:
            try:
                with open(password_file, "r") as f:
                    return f.read().strip()
            except FileNotFoundError:
                return None
        
        return None

    @field_validator("MISTRAL_API_KEY", mode="before")
    @classmethod
    def load_mistral_api_key_from_file(
        cls, v: str | None, values: dict[str, Any]
    ) -> str | None:
        """Load Mistral API key from file if MISTRAL_API_KEY_FILE is set."""
        if v is not None:
            return v
        
        api_key_file = values.get("MISTRAL_API_KEY_FILE")
        if api_key_file is not None:
            try:
                with open(api_key_file, "r") as f:
                    return f.read().strip()
            except FileNotFoundError:
                return None
        
        return None

    @field_validator("SESSION_SECRET", mode="before")
    @classmethod
    def load_session_secret_from_file(
        cls, v: str | None, values: dict[str, Any]
    ) -> str | None:
        """Load session secret from file if SESSION_SECRET_FILE is set."""
        if v is not None:
            return v
        
        secret_file = values.get("SESSION_SECRET_FILE")
        if secret_file is not None:
            try:
                with open(secret_file, "r") as f:
                    return f.read().strip()
            except FileNotFoundError:
                return None
        
        return None

    @property
    def admin_password(self) -> str | None:
        """Get admin password (from env or file)."""
        if self.ADMIN_PASSWORD is not None:
            return self.ADMIN_PASSWORD
        
        if self.ADMIN_PASSWORD_FILE is not None:
            try:
                with open(self.ADMIN_PASSWORD_FILE, "r") as f:
                    return f.read().strip()
            except FileNotFoundError:
                return None
        
        return None

    @property
    def mistral_api_key(self) -> str | None:
        """Get Mistral API key (from env or file)."""
        if self.MISTRAL_API_KEY is not None:
            return self.MISTRAL_API_KEY
        
        if self.MISTRAL_API_KEY_FILE is not None:
            try:
                with open(self.MISTRAL_API_KEY_FILE, "r") as f:
                    return f.read().strip()
            except FileNotFoundError:
                return None
        
        return None

    @property
    def session_secret(self) -> str | None:
        """Get session secret (from env or file)."""
        if self.SESSION_SECRET is not None:
            return self.SESSION_SECRET
        
        if self.SESSION_SECRET_FILE is not None:
            try:
                with open(self.SESSION_SECRET_FILE, "r") as f:
                    return f.read().strip()
            except FileNotFoundError:
                return None
        
        return None


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
