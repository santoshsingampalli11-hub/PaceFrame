"""HTTP routes for local pose-review jobs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.errors import error_payload
from app.api.pose_review_jobs import (
    ACTIVE_STATUSES,
    POSE_REVIEW_CAVEAT,
    DuplicatePoseReviewError,
    PoseReviewCapacityError,
    PoseReviewJob,
    STATUS_COMPLETED,
    STATUS_FAILED,
    get_job_runner,
    list_overlay_frames,
    load_completed_report,
    load_job,
    overlay_file,
    pose_review_dir,
)
from app.api.schemas import (
    PoseReviewJobResponse,
    PoseReviewReportResponse,
    PoseReviewRequest,
    PoseReviewStatus,
)
from app.api.session_access import SessionNotFound, SessionNotVerified, load_completed_session, load_verified_session
from app.api.session_store import InvalidSessionId
from app.api.settings import get_settings

router = APIRouter()

_LIMITATIONS = (
    "A detected pose is not proof that the person is the bowler.",
    "Visibility and presence are model scores, not landmark accuracy.",
    "This is not a 2D joint-angle measurement and not a 3D laboratory result.",
    "A matching video hash does not mean the recording is scientifically suitable.",
)


@router.post(
    "/sessions/{session_id}/pose-review",
    response_model=PoseReviewJobResponse,
    status_code=202,
    responses={
        400: {"content": {"application/json": {"example": error_payload("Invalid session id.")}}},
        404: {"content": {"application/json": {"example": error_payload("Session not found.")}}},
        409: {"content": {"application/json": {"example": error_payload("A pose review is already running for this session.")}}},
        503: {"content": {"application/json": {"example": error_payload("Pose review capacity is full.")}}},
    },
)
def start_pose_review(session_id: str, payload: PoseReviewRequest | None = None) -> PoseReviewJobResponse:
    """Queue a pose-review job for a verified uploaded video."""
    settings = get_settings()
    request = payload or PoseReviewRequest()
    frames = _validated_frames(request.review_frames, settings.max_review_frames)
    try:
        session = load_verified_session(settings.session_root, session_id)
    except InvalidSessionId as error:
        raise HTTPException(status_code=400, detail="Invalid session id.") from error
    except SessionNotFound as error:
        raise HTTPException(status_code=404, detail="Session not found.") from error
    except SessionNotVerified as error:
        raise HTTPException(status_code=400, detail="Video does not match the session manifest.") from error
    try:
        job = get_job_runner().submit(session, frames)
    except DuplicatePoseReviewError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PoseReviewCapacityError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except OSError:
        raise HTTPException(status_code=500, detail="Internal server error") from None
    return _job_response(job)


@router.get(
    "/sessions/{session_id}/pose-review",
    response_model=PoseReviewStatus,
)
def get_pose_review_status(session_id: str) -> PoseReviewStatus:
    """Return the current pose-review job status. This is not a measurement."""
    session = _completed_session(session_id)
    job = load_job(session.session_dir)
    if job is None or job.session_id != session_id:
        raise HTTPException(status_code=404, detail="No pose review job was found.")
    return PoseReviewStatus(
        session_id=job.session_id,
        job_id=job.job_id,
        status=job.status,
        message=job.message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        review_frames=list(job.review_frames),
        scientific_caveat=POSE_REVIEW_CAVEAT,
    )


@router.get(
    "/sessions/{session_id}/pose-review/report",
    response_model=PoseReviewReportResponse,
)
def get_pose_review_report(session_id: str) -> PoseReviewReportResponse:
    """Return the completed diagnostic report, or a non-success status."""
    session = _completed_session(session_id)
    job = load_job(session.session_dir)
    if job is None or job.session_id != session_id:
        raise HTTPException(status_code=404, detail="No pose review job was found.")
    if job.status in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Pose review is not complete.")
    if job.status == STATUS_FAILED:
        raise HTTPException(status_code=409, detail=job.error or "Pose review failed.")
    report = load_completed_report(session.session_dir)
    if report is None or job.status != STATUS_COMPLETED:
        raise HTTPException(status_code=409, detail="Pose review is not complete.")
    return PoseReviewReportResponse(
        session_id=report.job.session_id,
        job_id=report.job.job_id,
        status=report.job.status,
        report_text=report.report_text,
        pose_frames=report.pose_frames,
        decoded_frame_count=report.decoded_frame_count,
        missing_pose_count=report.missing_pose_count,
        scientific_caveat=POSE_REVIEW_CAVEAT,
        limitations=list(_LIMITATIONS),
        overlay_frames=list_overlay_frames(session.session_dir, tuple(job.review_frames)),
    )


@router.get(
    "/sessions/{session_id}/pose-review/frames/{frame_index}",
    responses={
        404: {"content": {"application/json": {"example": error_payload("No overlay was exported for that frame.")}}},
        409: {"content": {"application/json": {"example": error_payload("Pose review is not complete.")}}},
    },
)
def get_pose_review_frame(session_id: str, frame_index: int) -> FileResponse:
    """Return one already-exported overlay PNG. This does not draw a new pose."""
    if frame_index < 0:
        raise HTTPException(status_code=400, detail="Invalid frame index.")
    session = _completed_session(session_id)
    job = load_job(session.session_dir)
    if job is None or job.session_id != session_id:
        raise HTTPException(status_code=404, detail="No pose review job was found.")
    if job.status in ACTIVE_STATUSES or job.status == STATUS_FAILED or job.status != STATUS_COMPLETED:
        detail = job.error or "Pose review failed." if job.status == STATUS_FAILED else "Pose review is not complete."
        raise HTTPException(status_code=409, detail=detail)
    if frame_index not in job.review_frames:
        raise HTTPException(status_code=404, detail="No overlay was exported for that frame.")
    path = overlay_file(pose_review_dir(session.session_dir), frame_index)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="No overlay was exported for that frame.")
    return FileResponse(path, media_type="image/png", filename=path.name)


def _completed_session(session_id: str):
    settings = get_settings()
    try:
        return load_completed_session(settings.session_root, session_id)
    except InvalidSessionId as error:
        raise HTTPException(status_code=400, detail="Invalid session id.") from error
    except SessionNotFound as error:
        raise HTTPException(status_code=404, detail="Session not found.") from error


def _validated_frames(values: list[int], maximum: int) -> tuple[int, ...]:
    if len(values) > maximum:
        raise HTTPException(
            status_code=400,
            detail=f"At most {maximum} review frames can be requested.",
        )
    seen: set[int] = set()
    frames: list[int] = []
    for index in values:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise HTTPException(status_code=400, detail="Review frames must be non-negative integers.")
        if index in seen:
            raise HTTPException(status_code=400, detail="Review frames must not be repeated.")
        seen.add(index)
        frames.append(index)
    return tuple(frames)


def _job_response(job: PoseReviewJob) -> PoseReviewJobResponse:
    return PoseReviewJobResponse(
        session_id=job.session_id,
        job_id=job.job_id,
        status=job.status,
        status_path=f"/api/sessions/{job.session_id}/pose-review",
        message=job.message,
        scientific_caveat=POSE_REVIEW_CAVEAT,
    )
