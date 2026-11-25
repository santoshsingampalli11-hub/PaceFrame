"""FastAPI application entrypoint."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import http_exception_handler, unhandled_exception_handler
from app.api.http_guards import RateLimitGuard, TrustedHostGuard
from app.api.label_routes import router as label_router
from app.api.measurement_jobs import reset_measurement_runner
from app.api.measurement_routes import router as measurement_router
from app.api.pose_review_jobs import reset_job_runner
from app.api.pose_review_routes import router as pose_review_router
from app.api.routes import router
from app.api.session_routes import router as session_router
from app.api.settings import ensure_session_storage, get_settings
from app.api.upload_limit import UploadByteLimitMiddleware
from app.api.video_frame_routes import router as video_frame_router
from app.api.video_stream_routes import router as video_stream_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

LOCAL_VITE_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def cors_origins() -> list[str]:
    """Explicit browser origins. A wildcard is rejected. Credentials stay off."""
    raw = os.environ.get("FAST_BOWLING_CORS_ORIGINS", "").strip()
    if not raw:
        return list(LOCAL_VITE_ORIGINS)
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    if not origins or "*" in origins:
        raise RuntimeError("FAST_BOWLING_CORS_ORIGINS must list origins and must not contain *.")
    return origins


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_session_storage(get_settings())
    yield
    reset_job_runner()
    reset_measurement_runner()


app = FastAPI(
    title="Fast Bowling V1",
    version=__version__,
    lifespan=lifespan,
    description=(
        "Backend API for the Fast Bowling V1 prototype. "
        "Identification, health checks, delivery-session video upload, local "
        "pose-review jobs, manual event labels, and 2D front-knee measurement "
        "jobs are available. The original upload can be streamed for browser playback. "
        "A decoded upload or a detected pose is not a "
        "scientifically suitable recording. There is no user authentication. "
        "Run one Uvicorn process. Do not publish private session storage."
    ),
)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.include_router(router)
app.include_router(session_router, prefix="/api")
app.include_router(pose_review_router, prefix="/api")
app.include_router(label_router, prefix="/api")
app.include_router(measurement_router, prefix="/api")
app.include_router(video_frame_router, prefix="/api")
app.include_router(video_stream_router, prefix="/api")
app.add_middleware(UploadByteLimitMiddleware)
app.add_middleware(RateLimitGuard)
app.add_middleware(TrustedHostGuard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "Range"],
    expose_headers=["Accept-Ranges", "Content-Range", "Content-Length"],
)
