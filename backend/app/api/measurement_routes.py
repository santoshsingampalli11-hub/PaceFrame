"""HTTP routes for 2D front-knee measurement jobs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.errors import error_payload
from app.api.label_store import load_session_labels
from app.api.measurement_jobs import (
    ACTIVE_STATUSES,
    MEASURE_CAVEAT,
    DuplicateMeasurementError,
    MeasurementCapacityError,
    MeasurementJob,
    STATUS_COMPLETED,
    STATUS_FAILED,
    get_measurement_runner,
    load_measurement_job,
    load_measurement_report,
)
from app.api.schemas import MeasureJobResponse, MeasureRequest, MeasureStatus, MeasurementReportResponse
from app.api.session_access import SessionNotFound, SessionNotVerified, load_completed_session, load_verified_session
from app.api.session_store import InvalidSessionId, SessionStoreError
from app.api.settings import get_settings

router = APIRouter()


@router.post(
    "/sessions/{session_id}/measure",
    response_model=MeasureJobResponse,
    status_code=202,
    responses={
        400: {"content": {"application/json": {"example": error_payload("Labels are not ready for measurement.")}}},
        404: {"content": {"application/json": {"example": error_payload("Session not found.")}}},
        409: {"content": {"application/json": {"example": error_payload("A measurement is already running for this session.")}}},
        503: {"content": {"application/json": {"example": error_payload("Measurement capacity is full.")}}},
    },
)
def start_measurement(session_id: str, payload: MeasureRequest) -> MeasureJobResponse:
    """Queue a 2D front-knee measurement at the stored manual FFC and Release frames."""
    if payload.confirm_label_link is not True:
        raise HTTPException(
            status_code=400,
            detail="confirm_label_link must be true. A filename sidecar is not a SHA-256.",
        )
    settings = get_settings()
    try:
        session = load_verified_session(settings.session_root, session_id)
    except InvalidSessionId as error:
        raise HTTPException(status_code=400, detail="Invalid session id.") from error
    except SessionNotFound as error:
        raise HTTPException(status_code=404, detail="Session not found.") from error
    except SessionNotVerified as error:
        raise HTTPException(status_code=400, detail="Video does not match the session manifest.") from error
    try:
        labels = load_session_labels(session)
    except FileNotFoundError as error:
        raise HTTPException(status_code=400, detail="No labels were found.") from error
    except SessionStoreError as error:
        raise HTTPException(status_code=400, detail="Labels are not usable.") from error
    if not labels.confirm_label_link:
        raise HTTPException(
            status_code=400,
            detail="Label-link confirmation was not recorded for these annotations.",
        )
    if labels.ffc_frame is None or labels.release_frame is None:
        raise HTTPException(
            status_code=400,
            detail="FFC and Release frames are required before measurement. They are not detected automatically.",
        )
    if labels.front_leg not in {"left", "right"}:
        raise HTTPException(status_code=400, detail="The manifest has no anatomical front leg.")
    try:
        job = get_measurement_runner().submit(session)
    except DuplicateMeasurementError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except MeasurementCapacityError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except OSError:
        raise HTTPException(status_code=500, detail="Internal server error") from None
    return _job_response(job)


@router.get("/sessions/{session_id}/measure", response_model=MeasureStatus)
def get_measurement_status(session_id: str) -> MeasureStatus:
    session = _completed_session(session_id)
    job = load_measurement_job(session.session_dir)
    if job is None or job.session_id != session_id:
        raise HTTPException(status_code=404, detail="No measurement job was found.")
    return MeasureStatus(
        session_id=job.session_id,
        job_id=job.job_id,
        status=job.status,
        message=job.message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        scientific_caveat=MEASURE_CAVEAT,
    )


@router.get(
    "/sessions/{session_id}/report",
    response_model=MeasurementReportResponse,
)
def get_measurement_report(session_id: str) -> MeasurementReportResponse:
    session = _completed_session(session_id)
    job = load_measurement_job(session.session_dir)
    if job is None or job.session_id != session_id:
        raise HTTPException(status_code=404, detail="No measurement job was found.")
    if job.status in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Measurement is not complete.")
    if job.status == STATUS_FAILED:
        raise HTTPException(status_code=409, detail=job.error or "Measurement failed.")
    report = load_measurement_report(session.session_dir)
    if report is None or job.status != STATUS_COMPLETED:
        raise HTTPException(status_code=409, detail="Measurement is not complete.")
    _strip_paths(report)
    return MeasurementReportResponse(
        session_id=job.session_id,
        job_id=job.job_id,
        status=job.status,
        report=report,
        scientific_caveat=MEASURE_CAVEAT,
    )


def _completed_session(session_id: str):
    settings = get_settings()
    try:
        return load_completed_session(settings.session_root, session_id)
    except InvalidSessionId as error:
        raise HTTPException(status_code=400, detail="Invalid session id.") from error
    except SessionNotFound as error:
        raise HTTPException(status_code=404, detail="Session not found.") from error


def _job_response(job: MeasurementJob) -> MeasureJobResponse:
    return MeasureJobResponse(
        session_id=job.session_id,
        job_id=job.job_id,
        status=job.status,
        status_path=f"/api/sessions/{job.session_id}/measure",
        report_path=f"/api/sessions/{job.session_id}/report",
        message=job.message,
        scientific_caveat=MEASURE_CAVEAT,
    )


def _strip_paths(report: dict[str, object]) -> None:
    for key in list(report):
        if "path" in key.lower() and key != "report_type":
            del report[key]
