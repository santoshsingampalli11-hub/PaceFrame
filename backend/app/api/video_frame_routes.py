"""HTTP access to one exact original decoded frame. No pose estimation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.api.errors import error_payload
from app.api.session_access import SessionNotFound, SessionNotVerified, load_completed_session
from app.api.session_store import InvalidSessionId
from app.api.settings import get_settings
from app.api.video_frames import FrameAccessError, FrameCapacityError, original_frame_jpeg

router = APIRouter()


@router.get(
    "/sessions/{session_id}/video/frames/{frame_index}",
    responses={
        400: {"content": {"application/json": {"example": error_payload("Invalid frame index.")}}},
        404: {"content": {"application/json": {"example": error_payload("That decoded frame is not available.")}}},
        503: {"content": {"application/json": {"example": error_payload("Frame decoding capacity is full.")}}},
    },
)
def get_original_frame(session_id: str, frame_index: int) -> Response:
    """Return one JPEG of the exact zero-based decoded frame. The video file is not sent."""
    if frame_index < 0:
        raise HTTPException(status_code=400, detail="Invalid frame index.")
    settings = get_settings()
    try:
        session = load_completed_session(settings.session_root, session_id)
    except InvalidSessionId as error:
        raise HTTPException(status_code=400, detail="Invalid session id.") from error
    except SessionNotFound as error:
        raise HTTPException(status_code=404, detail="Session not found.") from error
    try:
        jpeg = original_frame_jpeg(session, frame_index)
    except SessionNotVerified as error:
        raise HTTPException(status_code=400, detail="Video does not match the session manifest.") from error
    except FrameCapacityError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except FrameAccessError as error:
        status = 400 if "Invalid" in str(error) or "outside" in str(error) else 404
        raise HTTPException(status_code=status, detail=str(error)) from error
    return Response(content=jpeg, media_type="image/jpeg")
