"""HTTP delivery of one verified original upload. No pose estimation and no transcoding."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from app.api.errors import error_payload
from app.api.session_access import SessionNotFound, SessionNotVerified, load_completed_session
from app.api.session_store import InvalidSessionId
from app.api.settings import get_settings
from app.api.video_stream import (
    RangeNotSatisfiable,
    RangeNotSupported,
    iter_file_span,
    media_type_for_filename,
    parse_byte_range,
    verified_video_size,
)

router = APIRouter()


@router.api_route(
    "/sessions/{session_id}/video",
    methods=["GET", "HEAD"],
    responses={
        200: {"content": {"video/mp4": {}}},
        206: {"description": "A single byte range of the original upload."},
        400: {"content": {"application/json": {"example": error_payload("Invalid session id.")}}},
        404: {"content": {"application/json": {"example": error_payload("Session not found.")}}},
        416: {"description": "The requested byte range is outside the video."},
    },
)
def get_original_video(session_id: str, request: Request) -> Response:
    """Stream the stored upload. MP4, MOV, and AVI are not transcoded.

    Browser playback depends on the codec inside the container. This local
    prototype does not authenticate callers.
    """
    settings = get_settings()
    try:
        session = load_completed_session(settings.session_root, session_id)
        total = verified_video_size(session)
        span = parse_byte_range(request.headers.get("range"), total)
    except InvalidSessionId as error:
        raise HTTPException(status_code=400, detail="Invalid session id.") from error
    except SessionNotFound as error:
        raise HTTPException(status_code=404, detail="Session not found.") from error
    except SessionNotVerified as error:
        raise HTTPException(status_code=400, detail="Video does not match the session manifest.") from error
    except (RangeNotSatisfiable, RangeNotSupported) as error:
        return _unsatisfiable(total_from_error(session_id), error)

    media_type = media_type_for_filename(session.video_path.name)
    filename = session.video_path.name
    if span is None:
        start, end, status = 0, max(total - 1, 0), 200
        range_header = None
        length = total
    else:
        start, end, status = span.start, span.end, 206
        range_header = f"bytes {start}-{end}/{total}"
        length = span.length
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": f'inline; filename="{filename}"',
    }
    if range_header is not None:
        headers["Content-Range"] = range_header
    if request.method == "HEAD" or length == 0:
        return Response(status_code=status, media_type=media_type, headers=headers)
    return StreamingResponse(
        iter_file_span(session.video_path, start, end),
        status_code=status,
        media_type=media_type,
        headers=headers,
    )


def _unsatisfiable(total: int | None, error: Exception) -> Response:
    headers = {"Accept-Ranges": "bytes"}
    if total is not None and total >= 0:
        headers["Content-Range"] = f"bytes */{total}"
    status = 416
    if isinstance(error, RangeNotSupported):
        status = 416
    return Response(status_code=status, headers=headers, content=b"")


def total_from_error(session_id: str) -> int | None:
    """Best-effort size for a 416 header. Never opens a path from the caller."""
    try:
        settings = get_settings()
        session = load_completed_session(settings.session_root, session_id)
        return session.video_path.stat().st_size
    except (InvalidSessionId, SessionNotFound, OSError):
        return None
