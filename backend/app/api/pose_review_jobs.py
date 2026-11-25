"""Process-local pose-review jobs. Not a distributed queue."""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.api.errors import public_detail
from app.api.session_access import (
    SessionNotFound,
    SessionNotVerified,
    VerifiedSession,
    load_verified_session,
)
from app.api.session_store import (
    SESSION_ID_PATTERN,
    InvalidSessionId,
    SessionStoreError,
    write_json_replace,
)
from app.api.settings import ApiSettings, get_settings
from app.pose.estimator import PoseEstimationError, PoseEstimator
from app.quality.pilot_review import PilotReviewError, run_pilot_review

logger = logging.getLogger("fast_bowling.api")

JOB_ID_PATTERN = SESSION_ID_PATTERN
POSE_REVIEW_DIRNAME = "pose_review"
JOB_RECORD_NAME = "job.json"
REPORT_NAME = "report.txt"
SUMMARY_NAME = "summary.json"
STAGING_DIRNAME = "staging"
PRESERVED_DIRNAME = "_preserved"

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
ACTIVE_STATUSES = {STATUS_QUEUED, STATUS_RUNNING}

POSE_REVIEW_CAVEAT = (
    "A completed pose review is a diagnostic summary of MediaPipe detections. "
    "It is not a 2D or 3D biomechanical measurement, not bowler identity, and "
    "not proof that the recording is scientifically suitable."
)
_INTERRUPTED = "Pose review was interrupted when the server stopped."
_FAILED = "Pose review failed."
_FIELD = re.compile(r"^(pose_frames|decoded_frame_count|missing_pose_count): (.+)$", re.MULTILINE)

EstimatorFactory = Callable[[], PoseEstimator]


class DuplicatePoseReviewError(RuntimeError):
    """This session already has a queued or running pose review."""


class PoseReviewCapacityError(RuntimeError):
    """The local process already has the maximum number of pose-review jobs."""


class PoseReviewJobError(ValueError):
    """The pose-review job could not be started or read."""


@dataclass(frozen=True)
class PoseReviewJob:
    """Safe job metadata. Absolute paths are not included."""

    job_id: str
    session_id: str
    status: str
    message: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    review_frames: tuple[int, ...]
    error: str | None


@dataclass(frozen=True)
class PoseReviewReport:
    """Completed diagnostic report. Detection is not measurement accuracy."""

    job: PoseReviewJob
    report_text: str
    pose_frames: int | None
    decoded_frame_count: int | None
    missing_pose_count: int | None


_estimator_factory_override: EstimatorFactory | None = None
_runner: "PoseReviewRunner | None" = None
_runner_lock = threading.Lock()


def default_estimator_factory() -> PoseEstimator:
    from app.pose.mediapipe_estimator import MediaPipePoseEstimator

    return MediaPipePoseEstimator()


def get_estimator_factory() -> EstimatorFactory:
    if _estimator_factory_override is not None:
        return _estimator_factory_override
    return default_estimator_factory


def set_estimator_factory(factory: EstimatorFactory | None) -> None:
    global _estimator_factory_override
    _estimator_factory_override = factory


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pose_review_dir(session_dir: Path) -> Path:
    return session_dir / POSE_REVIEW_DIRNAME


def load_job(session_dir: Path) -> PoseReviewJob | None:
    path = pose_review_dir(session_dir) / JOB_RECORD_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return _job_from_payload(data)
    except PoseReviewJobError:
        return None


def save_job(session_dir: Path, job: PoseReviewJob) -> None:
    write_json_replace(
        pose_review_dir(session_dir) / JOB_RECORD_NAME,
        {
            "job_id": job.job_id,
            "session_id": job.session_id,
            "status": job.status,
            "message": job.message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "review_frames": list(job.review_frames),
            "error": job.error,
        },
    )


def load_completed_report(session_dir: Path) -> PoseReviewReport | None:
    job = load_job(session_dir)
    if job is None or job.status != STATUS_COMPLETED:
        return None
    report_path = pose_review_dir(session_dir) / REPORT_NAME
    if not report_path.is_file():
        return None
    try:
        text = report_path.read_text(encoding="utf-8")
    except OSError:
        return None
    fields = {name: _optional_int(value) for name, value in _FIELD.findall(text)}
    return PoseReviewReport(
        job=job,
        report_text=text,
        pose_frames=fields.get("pose_frames"),
        decoded_frame_count=fields.get("decoded_frame_count"),
        missing_pose_count=fields.get("missing_pose_count"),
    )


def mark_interrupted_jobs(root: Path) -> None:
    """Mark queued/running jobs failed after a process restart. Reports are not left completed."""
    if not root.is_dir():
        return
    for child in root.iterdir():
        if not child.is_dir() or not SESSION_ID_PATTERN.fullmatch(child.name):
            continue
        job = load_job(child)
        if job is None or job.status not in ACTIVE_STATUSES:
            continue
        if _restore_preserved(child):
            continue
        _discard_outputs(pose_review_dir(child))
        save_job(
            child,
            PoseReviewJob(
                job_id=job.job_id,
                session_id=job.session_id,
                status=STATUS_FAILED,
                message=_INTERRUPTED,
                created_at=job.created_at,
                started_at=job.started_at,
                finished_at=utc_now(),
                review_frames=job.review_frames,
                error=_INTERRUPTED,
            ),
        )


class PoseReviewRunner:
    """Thread pool with a hard cap. State is process-local except the on-disk job record."""

    def __init__(self, settings: ApiSettings, estimator_factory: EstimatorFactory) -> None:
        self._settings = settings
        self._estimator_factory = estimator_factory
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._active = 0
        self._inflight_sessions: set[str] = set()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_pose_jobs,
            thread_name_prefix="pose-review",
        )
        mark_interrupted_jobs(settings.session_root)

    def submit(self, session: VerifiedSession, review_frames: tuple[int, ...]) -> PoseReviewJob:
        job = PoseReviewJob(
            job_id=secrets.token_hex(16),
            session_id=session.session_id,
            status=STATUS_QUEUED,
            message="Pose review is queued. Detection is not measurement accuracy.",
            created_at=utc_now(),
            started_at=None,
            finished_at=None,
            review_frames=review_frames,
            error=None,
        )
        with self._lock:
            if session.session_id in self._inflight_sessions:
                raise DuplicatePoseReviewError("A pose review is already running for this session.")
            current = load_job(session.session_dir)
            if current is not None and current.status in ACTIVE_STATUSES:
                raise DuplicatePoseReviewError("A pose review is already running for this session.")
            if self._active >= self._settings.max_pose_jobs:
                raise PoseReviewCapacityError("Pose review capacity is full.")
            _preserve_completed(session.session_dir)
            save_job(session.session_dir, job)
            self._inflight_sessions.add(session.session_id)
            self._active += 1
            accepted = True
        if accepted:
            self._executor.submit(self._run, session.session_id, job.job_id)
        return job

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _run(self, session_id: str, job_id: str) -> None:
        session_dir: Path | None = None
        try:
            session = load_verified_session(self._settings.session_root, session_id)
            session_dir = session.session_dir
            job = load_job(session_dir)
            if job is None or job.job_id != job_id:
                return
            save_job(
                session_dir,
                PoseReviewJob(
                    job_id=job.job_id,
                    session_id=job.session_id,
                    status=STATUS_RUNNING,
                    message="Pose review is running. This is not a biomechanics measurement.",
                    created_at=job.created_at,
                    started_at=utc_now(),
                    finished_at=None,
                    review_frames=job.review_frames,
                    error=None,
                ),
            )
            self._execute(session, job)
        except (InvalidSessionId, SessionNotFound, SessionNotVerified, SessionStoreError) as error:
            logger.info("Pose review could not use session %s: %s", session_id, type(error).__name__)
            if session_dir is not None:
                self._fail(session_dir, job_id, "Session could not be verified.")
        except Exception:
            logger.exception("Pose review worker failed")
            if session_dir is not None:
                self._fail(session_dir, job_id, _FAILED)
        finally:
            with self._lock:
                self._inflight_sessions.discard(session_id)
                if self._active > 0:
                    self._active -= 1
                self._idle.notify_all()

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        """Block until no queued or running jobs remain. For tests, not the HTTP API."""
        with self._lock:
            return self._idle.wait_for(lambda: self._active == 0, timeout=timeout)

    def _execute(self, session: VerifiedSession, job: PoseReviewJob) -> None:
        review_root = pose_review_dir(session.session_dir)
        staging = review_root / STAGING_DIRNAME
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            try:
                estimator = self._estimator_factory()
            except PoseEstimationError as error:
                self._fail(
                    session.session_dir,
                    job.job_id,
                    public_detail(str(error), "The pose model could not be loaded."),
                )
                return
            try:
                result = run_pilot_review(
                    session.video_path,
                    staging,
                    job.review_frames,
                    estimator=estimator,
                )
            except PilotReviewError as error:
                self._fail(
                    session.session_dir,
                    job.job_id,
                    public_detail(str(error), _FAILED),
                )
                return
            if result.error or result.report_path is None:
                self._fail(
                    session.session_dir,
                    job.job_id,
                    public_detail(result.error or _FAILED, _FAILED),
                )
                return
            report_destination = review_root / REPORT_NAME
            if report_destination.exists():
                report_destination.unlink()
            result.report_path.replace(report_destination)
            text = report_destination.read_text(encoding="utf-8")
            fields = {name: _optional_int(value) for name, value in _FIELD.findall(text)}
            write_json_replace(
                review_root / SUMMARY_NAME,
                {
                    "pose_frames": fields.get("pose_frames"),
                    "decoded_frame_count": fields.get("decoded_frame_count"),
                    "missing_pose_count": fields.get("missing_pose_count"),
                },
            )
            _promote_overlays(staging, review_root, job.review_frames)
            current = load_job(session.session_dir)
            if current is None or current.job_id != job.job_id:
                return
            save_job(
                session.session_dir,
                PoseReviewJob(
                    job_id=job.job_id,
                    session_id=job.session_id,
                    status=STATUS_COMPLETED,
                    message=(
                        "Pose review completed. Detection is not measurement accuracy "
                        "and does not confirm recording suitability."
                    ),
                    created_at=current.created_at,
                    started_at=current.started_at,
                    finished_at=utc_now(),
                    review_frames=job.review_frames,
                    error=None,
                ),
            )
            preserved = review_root / PRESERVED_DIRNAME
            if preserved.exists():
                shutil.rmtree(preserved, ignore_errors=True)
        except OSError:
            logger.exception("Pose review could not write its report")
            self._fail(session.session_dir, job.job_id, _FAILED)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _fail(self, session_dir: Path, job_id: str, message: str) -> None:
        current = load_job(session_dir)
        if current is None or current.job_id != job_id:
            return
        if _restore_preserved(session_dir):
            return
        _discard_outputs(pose_review_dir(session_dir))
        save_job(
            session_dir,
            PoseReviewJob(
                job_id=current.job_id,
                session_id=current.session_id,
                status=STATUS_FAILED,
                message=message,
                created_at=current.created_at,
                started_at=current.started_at,
                finished_at=utc_now(),
                review_frames=current.review_frames,
                error=message,
            ),
        )


def get_job_runner() -> PoseReviewRunner:
    global _runner
    with _runner_lock:
        if _runner is None:
            _runner = PoseReviewRunner(get_settings(), get_estimator_factory())
        return _runner


def reset_job_runner() -> None:
    global _runner
    with _runner_lock:
        if _runner is not None:
            _runner.shutdown()
            _runner = None


def _job_from_payload(payload: dict[str, object]) -> PoseReviewJob:
    job_id = payload.get("job_id")
    session_id = payload.get("session_id")
    status = payload.get("status")
    message = payload.get("message")
    created_at = payload.get("created_at")
    started_at = payload.get("started_at")
    finished_at = payload.get("finished_at")
    frames = payload.get("review_frames")
    error = payload.get("error")
    if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
        raise PoseReviewJobError("Invalid job record.")
    if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
        raise PoseReviewJobError("Invalid job record.")
    if status not in {STATUS_QUEUED, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED}:
        raise PoseReviewJobError("Invalid job record.")
    if not isinstance(message, str) or not message:
        raise PoseReviewJobError("Invalid job record.")
    if not isinstance(created_at, str) or not created_at:
        raise PoseReviewJobError("Invalid job record.")
    if started_at is not None and not isinstance(started_at, str):
        raise PoseReviewJobError("Invalid job record.")
    if finished_at is not None and not isinstance(finished_at, str):
        raise PoseReviewJobError("Invalid job record.")
    if not isinstance(frames, list) or any(
        isinstance(index, bool) or not isinstance(index, int) or index < 0 for index in frames
    ):
        raise PoseReviewJobError("Invalid job record.")
    if error is not None and not isinstance(error, str):
        raise PoseReviewJobError("Invalid job record.")
    return PoseReviewJob(
        job_id=job_id,
        session_id=session_id,
        status=status,
        message=message,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
        review_frames=tuple(frames),
        error=error,
    )


def overlay_file(review_root: Path, frame_index: int) -> Path | None:
    """Return the server-named overlay PNG if the index cannot escape the review folder."""
    if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
        return None
    name = f"frame_{frame_index}.png"
    try:
        root = review_root.resolve()
        path = (root / name).resolve()
    except OSError:
        return None
    if path.parent != root or path.name != name:
        return None
    return path


def list_overlay_frames(session_dir: Path, frame_indexes: tuple[int, ...]) -> list[int]:
    """Indexes whose exported overlay PNG is still present. Missing files are omitted."""
    root = pose_review_dir(session_dir)
    present: list[int] = []
    for index in frame_indexes:
        path = overlay_file(root, index)
        if path is not None and path.is_file():
            present.append(index)
    return present


def _preserve_completed(session_dir: Path) -> None:
    """Copy a completed review aside before a rerun replaces the job record."""
    review = pose_review_dir(session_dir)
    preserved = review / PRESERVED_DIRNAME
    if preserved.exists():
        shutil.rmtree(preserved, ignore_errors=True)
    job = load_job(session_dir)
    if job is None or job.status != STATUS_COMPLETED or not (review / REPORT_NAME).is_file():
        return
    preserved.mkdir(parents=True, exist_ok=True)
    for name in (JOB_RECORD_NAME, REPORT_NAME, SUMMARY_NAME):
        source = review / name
        if source.is_file():
            shutil.copy2(source, preserved / name)
    for png in review.glob("frame_*.png"):
        if png.is_file():
            shutil.copy2(png, preserved / png.name)


def _restore_preserved(session_dir: Path) -> bool:
    """Put the previous successful review back. Return False when there is none."""
    review = pose_review_dir(session_dir)
    preserved = review / PRESERVED_DIRNAME
    previous_job = preserved / JOB_RECORD_NAME
    if not previous_job.is_file():
        return False
    for png in review.glob("frame_*.png"):
        if png.is_file():
            png.unlink()
    for png in preserved.glob("frame_*.png"):
        if png.is_file():
            shutil.copy2(png, review / png.name)
    for name in (REPORT_NAME, SUMMARY_NAME, JOB_RECORD_NAME):
        source = preserved / name
        target = review / name
        if source.is_file():
            shutil.copy2(source, target)
        elif target.is_file() and name != JOB_RECORD_NAME:
            target.unlink()
    staging = review / STAGING_DIRNAME
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(preserved, ignore_errors=True)
    return True


def _promote_overlays(staging: Path, review_root: Path, frame_indexes: tuple[int, ...]) -> None:
    """Move requested overlay PNGs out of staging. Other files stay behind and are deleted."""
    for existing in review_root.glob("frame_*.png"):
        if existing.is_file():
            existing.unlink()
    for index in frame_indexes:
        destination = overlay_file(review_root, index)
        if destination is None:
            continue
        source = staging / destination.name
        if source.is_file():
            source.replace(destination)


def _discard_outputs(review_root: Path) -> None:
    for name in (REPORT_NAME, SUMMARY_NAME):
        path = review_root / name
        path.unlink(missing_ok=True)
    for existing in review_root.glob("frame_*.png"):
        if existing.is_file():
            existing.unlink()
    staging = review_root / STAGING_DIRNAME
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)


def _optional_int(value: str) -> int | None:
    text = value.strip()
    if text == "unavailable":
        return None
    try:
        return int(text)
    except ValueError:
        return None
