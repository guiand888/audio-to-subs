"""Application version endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel

from audio_to_subs import __version__

router = APIRouter(prefix="/api", tags=["version"])


class VersionResponse(BaseModel):
    """Running application version."""

    version: str


@router.get("/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    """Return the running application version.

    Public (no authentication) so the login screen and unauthenticated
    states can display it. The version is baked into the package at build
    time from the repo-root VERSION file (see setup.py / pyproject.toml) and
    fetched by the frontend from this endpoint.
    """
    return VersionResponse(version=__version__)
