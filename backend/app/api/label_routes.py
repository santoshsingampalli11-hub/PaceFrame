"""HTTP routes for manual bowling-phase labels."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.annotations.models import AnnotationError
from app.api.errors import error_payload, public_detail
from app.api.label_store import (
    FrontLegConflictError,
    LabelConflictError,
    StoredLabels,
    load_session_labels,
    save_session_labels,
)
from app.api.schemas import SessionLabelsRequest, SessionLabelsResponse
from app.api.session_access import SessionNotFound, SessionNotVerified, load_completed_session, load_verified_session
from app.api.session_store import InvalidSessionId, SessionStoreError
from app.api.settings import get_settings

router = APIRouter()

LABEL_CAVEAT = (
    "These frames are annotator-selected indexes, not automatic detections "
    "and not laboratory ground truth. A matching filename sidecar is not a SHA-256."
)


@router.put(
    "/sessions/{session_id}/labels",
    response_model=SessionLabelsResponse,
    responses={
        400: {"content": {"application/json": {"example": error_payload("Invalid labels.")}}},
        404: {"content": {"application/json": {"example": error_payload("Session not found.")}}},
        409: {"content": {"application/json": {"example": error_payload("Labels already exist for this session.")}}},
    },
)
def put_session_labels(session_id: str, payload: SessionLabelsRequest) -> SessionLabelsResponse:
    """Store manual BFC/FFC/Release frames for a verified session."""
    session = _verified_session(session_id)
    labeler = payload.labeler.strip()
    if not labeler or any(character in labeler for character in '/\\:') or any(ord(ch) < 32 for ch in labeler):
        raise HTTPException(status_code=400, detail="labeler must be a non-empty anonymous identifier.")
    try:
        stored = save_session_labels(
            session,
            bfc_frame=payload.bfc_frame,
            ffc_frame=payload.ffc_frame,
            release_frame=payload.release_frame,
            front_leg=payload.front_leg,
            confirm_front_leg=payload.confirm_front_leg,
            confirm_label_link=payload.confirm_label_link,
            labeler=labeler,
            notes=payload.notes,
            replace_existing=payload.replace_existing,
        )
    except LabelConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FrontLegConflictError as error:
        raise HTTPException(status_code=409, detail=public_detail(str(error), "front_leg was not changed.")) from error
    except AnnotationError as error:
        raise HTTPException(status_code=400, detail=public_detail(str(error), "Invalid labels.")) from error
    except SessionStoreError as error:
        raise HTTPException(status_code=400, detail=public_detail(str(error), "Invalid labels.")) from error
    return _labels_response(stored)


@router.get(
    "/sessions/{session_id}/labels",
    response_model=SessionLabelsResponse,
)
def get_session_labels(session_id: str) -> SessionLabelsResponse:
    """Return stored manual labels. Corrupt files are not treated as valid."""
    settings = get_settings()
    try:
        session = load_completed_session(settings.session_root, session_id)
    except InvalidSessionId as error:
        raise HTTPException(status_code=400, detail="Invalid session id.") from error
    except SessionNotFound as error:
        raise HTTPException(status_code=404, detail="Session not found.") from error
    try:
        stored = load_session_labels(session)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="No labels were found.") from error
    except SessionStoreError as error:
        raise HTTPException(status_code=404, detail="Labels are not usable.") from error
    return _labels_response(stored)


def _verified_session(session_id: str):
    settings = get_settings()
    try:
        return load_verified_session(settings.session_root, session_id)
    except InvalidSessionId as error:
        raise HTTPException(status_code=400, detail="Invalid session id.") from error
    except SessionNotFound as error:
        raise HTTPException(status_code=404, detail="Session not found.") from error
    except SessionNotVerified as error:
        raise HTTPException(status_code=400, detail="Video does not match the session manifest.") from error


def _labels_response(stored: StoredLabels) -> SessionLabelsResponse:
    return SessionLabelsResponse(
        session_id=stored.session_id,
        bowler_id=stored.bowler_id,
        delivery_id=stored.delivery_id,
        video_filename=stored.video_filename,
        bfc_frame=stored.bfc_frame,
        ffc_frame=stored.ffc_frame,
        release_frame=stored.release_frame,
        labeler=stored.labeler,
        notes=stored.notes,
        front_leg=stored.front_leg,
        confirm_front_leg=stored.confirm_front_leg,
        confirm_label_link=stored.confirm_label_link,
        annotation_provenance=stored.annotation_provenance,
        annotation_byte_identity_verified=stored.annotation_byte_identity_verified,
        scientific_caveat=LABEL_CAVEAT,
    )
