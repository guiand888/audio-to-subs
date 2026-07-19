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
    states can display it. Mirrors the version baked into the frontend
    bundle; both derive from the same APP_VERSION build arg.
    """
    return VersionResponse(version=__version__)
