"""HTTP routes for the current API foundation."""

from fastapi import APIRouter

from app import __version__
from app.api.schemas import HealthResponse, RootResponse

router = APIRouter()


@router.get("/", response_model=RootResponse)
def root() -> RootResponse:
    """Identify the API."""
    return RootResponse(name="Fast Bowling V1", version=__version__)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API process is running."""
    return HealthResponse(status="healthy")
