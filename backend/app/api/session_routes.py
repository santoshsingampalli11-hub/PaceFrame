"""HTTP routes that create and read delivery sessions from uploaded videos."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.api.errors import error_payload
from app.api.schemas import SessionResponse
from app.api.session_store import (
    ALLOWED_ORIENTATIONS,
    DuplicateSessionError,
    InvalidSessionId,
    MANIFEST_NAME,
    SESSION_RECORD_NAME,
    SESSION_STATUS_CREATED,
    SessionRecord,
    SessionStoreError,
    UploadLimitExceeded,
    allocate_session_dir,
    client_filename,
    extension_for_filename,
    is_allowed_video_extension,
    is_archive_extension,
    load_session_record,
    remove_session_dir,
    resolve_session_dir,
    save_upload_limited,
    stored_video_filename,
    write_session_record,
)
from app.api.settings import get_settings
from app.pilot.session_manifest import (
    SessionManifestError,
    create_session_manifest,
    load_session_manifest,
)
from app.video.inspect import inspect_video

logger = logging.getLogger("fast_bowling.api")

router = APIRouter()

SCIENTIFIC_CAVEAT = (
    "Decoding and a matching file hash do not mean this video is suitable "
    "for biomechanical analysis. Side-on view and full-body visibility stay "
    "unconfirmed until a person reviews them. Encoded FPS is the container "
    "rate, not a measured capture clock."
)
_BOWLER_PREFIX = "B"
_DELIVERY_PREFIX = "D"
_PATH_HINT = re.compile(r"[A-Za-z]:\\|\\\\|/Users/|/home/|\\Users\\")


@router.post(
    "/sessions",
    response_model=SessionResponse,
    responses={
        400: {"content": {"application/json": {"example": error_payload("Video could not be decoded.")}}},
        413: {"content": {"application/json": {"example": error_payload("Upload exceeds the configured size limit.")}}},
        415: {"content": {"application/json": {"example": error_payload("Unsupported video format.")}}},
    },
)
async def create_session(
    request: Request,
    video: UploadFile = File(...),
    bowler_id: str = Form(...),
    delivery_id: str = Form(...),
    front_leg: str | None = Form(None),
) -> SessionResponse:
    """Store one uploaded video and write a verified session manifest."""
    settings = get_settings()
    bowler = _anonymous_id("bowler_id", bowler_id, _BOWLER_PREFIX)
    delivery = _anonymous_id("delivery_id", delivery_id, _DELIVERY_PREFIX)
    leg = _optional_front_leg(front_leg)
    try:
        original_name = client_filename(video.filename)
    except SessionStoreError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    extension = extension_for_filename(original_name)
    if is_archive_extension(extension) or not is_allowed_video_extension(extension):
        raise HTTPException(status_code=415, detail="Unsupported video format.")

    header_length = request.headers.get("content-length")
    if header_length is not None:
        try:
            declared = int(header_length)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid Content-Length.") from error
        if declared > settings.max_request_bytes:
            raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit.")

    try:
        session_id, session_dir = allocate_session_dir(settings.session_root)
    except DuplicateSessionError as error:
        raise HTTPException(status_code=409, detail="Session id already exists.") from error
    except SessionStoreError as error:
        logger.exception("Session allocation failed: %s", type(error).__name__)
        raise HTTPException(status_code=500, detail="Internal server error") from error

    committed = False
    try:
        stored_name = stored_video_filename(extension)
        destination = session_dir / stored_name
        try:
            await save_upload_limited(video, destination, settings.max_upload_bytes)
        except UploadLimitExceeded as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        except SessionStoreError as error:
            raise HTTPException(status_code=400, detail=_public_error(str(error))) from error

        inspection = inspect_video(destination)
        if (
            inspection.error
            or inspection.width is None
            or inspection.height is None
            or inspection.encoded_fps is None
            or inspection.reported_frame_count is None
            or inspection.decoded_frame_count is None
            or inspection.orientation not in ALLOWED_ORIENTATIONS
        ):
            raise HTTPException(status_code=400, detail="Video could not be decoded.")

        try:
            manifest = create_session_manifest(
                destination,
                bowler,
                delivery,
                session_dir / MANIFEST_NAME,
                leg,
            )
        except SessionManifestError as error:
            raise HTTPException(status_code=400, detail=_public_error(str(error))) from error

        record = SessionRecord(
            session_id=session_id,
            status=SESSION_STATUS_CREATED,
            stored_filename=stored_name,
            orientation=inspection.orientation,
        )
        try:
            write_session_record(session_dir, record)
        except SessionStoreError:
            logger.exception("Session record was not written")
            raise HTTPException(status_code=500, detail="Internal server error") from None
        committed = True
        return _session_response(record, manifest)
    except HTTPException:
        raise
    except OSError:
        logger.exception("Session storage failed")
        raise HTTPException(status_code=500, detail="Internal server error") from None
    finally:
        if not committed:
            remove_session_dir(settings.session_root, session_dir)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    responses={
        400: {"content": {"application/json": {"example": error_payload("Invalid session id.")}}},
        404: {"content": {"application/json": {"example": error_payload("Session not found.")}}},
    },
)
def get_session(session_id: str) -> SessionResponse:
    """Return a stored session manifest summary. Absolute paths are not included."""
    settings = get_settings()
    try:
        session_dir = resolve_session_dir(settings.session_root, session_id)
    except InvalidSessionId as error:
        raise HTTPException(status_code=400, detail="Invalid session id.") from error
    record_path = session_dir / SESSION_RECORD_NAME
    manifest_path = session_dir / MANIFEST_NAME
    if not record_path.is_file() or not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        record = load_session_record(session_dir)
        manifest = load_session_manifest(manifest_path)
    except (SessionStoreError, SessionManifestError) as error:
        raise HTTPException(status_code=404, detail="Session not found.") from error
    stored_video = session_dir / record.stored_filename
    if record.session_id != session_id or not stored_video.is_file():
        raise HTTPException(status_code=404, detail="Session not found.")
    return _session_response(record, manifest)


def _session_response(record: SessionRecord, manifest: object) -> SessionResponse:
    return SessionResponse(
        session_id=record.session_id,
        bowler_id=manifest.bowler_id,
        delivery_id=manifest.delivery_id,
        video_filename=record.stored_filename,
        video_sha256=manifest.video_sha256,
        width=manifest.width,
        height=manifest.height,
        encoded_fps=manifest.encoded_fps,
        decoded_frame_count=manifest.decoded_frame_count,
        orientation=record.orientation,
        status=record.status,
        front_leg=manifest.front_leg,
        camera_side_on_confirmed=manifest.camera_side_on_confirmed,
        full_body_visibility_confirmed=manifest.full_body_visibility_confirmed,
        scientific_caveat=SCIENTIFIC_CAVEAT,
    )


def _anonymous_id(field_name: str, value: str, prefix: str) -> str:
    text = value.strip()
    digits = text[1:] if text else ""
    if not text.startswith(prefix) or not digits.isascii() or not digits.isdecimal() or len(digits) < 2:
        raise HTTPException(status_code=400, detail=f"{field_name} must look like {prefix}01.")
    return text


def _optional_front_leg(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text not in {"left", "right"}:
        raise HTTPException(
            status_code=400,
            detail="front_leg must be left, right, or omitted.",
        )
    return text


def _public_error(message: str) -> str:
    if _PATH_HINT.search(message):
        return "The session could not be created."
    return message
