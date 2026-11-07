"""Process-local front-knee measurement jobs. Not a distributed queue."""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.api.errors import public_detail
from app.api.label_store import labels_path, load_session_labels
from app.api.pose_review_jobs import (
    ACTIVE_STATUSES,
    JOB_ID_PATTERN,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    EstimatorFactory,
    get_estimator_factory,
    utc_now,
)
from app.api.session_access import (
    SessionNotFound,
    SessionNotVerified,
    VerifiedSession,
    load_verified_session,
)
from app.api.session_store import (
    MANIFEST_NAME,
    SESSION_ID_PATTERN,
    InvalidSessionId,
    SessionStoreError,
    write_json_replace,
)
from app.api.settings import ApiSettings, get_settings
from app.pilot.manual_measurement import measure_manual_front_knee
from app.pose.estimator import PoseEstimationError

logger = logging.getLogger("fast_bowling.api")

MEASURE_DIRNAME = "measurement"
JOB_RECORD_NAME = "job.json"
REPORT_NAME = "report.json"
STAGING_DIRNAME = "staging"
MEASURE_CAVEAT = (
    "These are 2D image-plane front-knee angles at manual FFC and Release frames. "
    "They are not 3D joint angles, technique scores, or injury estimates. "
    "Unavailable is not zero degrees."
)
_INTERRUPTED = "Measurement was interrupted when the server stopped."
_FAILED = "Measurement failed."


class DuplicateMeasurementError(RuntimeError):
    """This session already has a queued, running, or completed measurement."""


class MeasurementCapacityError(RuntimeError):
    """The local process already has the maximum number of measurement jobs."""


class MeasurementJobError(ValueError):
    """The measurement job could not be started or read."""


@dataclass(frozen=True)
class MeasurementJob:
    job_id: str
    session_id: str
    status: str
    message: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    error: str | None


_runner: "MeasurementRunner | None" = None
_runner_lock = threading.Lock()


def measure_dir(session_dir: Path) -> Path:
    return session_dir / MEASURE_DIRNAME


def report_path(session_dir: Path) -> Path:
    return measure_dir(session_dir) / REPORT_NAME


def load_measurement_job(session_dir: Path) -> MeasurementJob | None:
    path = measure_dir(session_dir) / JOB_RECORD_NAME
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
    except MeasurementJobError:
        return None


def save_measurement_job(session_dir: Path, job: MeasurementJob) -> None:
    write_json_replace(
        measure_dir(session_dir) / JOB_RECORD_NAME,
        {
            "job_id": job.job_id,
            "session_id": job.session_id,
            "status": job.status,
            "message": job.message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "error": job.error,
        },
    )


def load_measurement_report(session_dir: Path) -> dict[str, object] | None:
    job = load_measurement_job(session_dir)
    path = report_path(session_dir)
    if job is None or job.status != STATUS_COMPLETED or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def mark_interrupted_measurements(root: Path) -> None:
    if not root.is_dir():
        return
    for child in root.iterdir():
        if not child.is_dir() or not SESSION_ID_PATTERN.fullmatch(child.name):
            continue
        job = load_measurement_job(child)
        if job is None or job.status not in ACTIVE_STATUSES:
            continue
        _discard_incomplete(measure_dir(child))
        save_measurement_job(
            child,
            MeasurementJob(
                job_id=job.job_id,
                session_id=job.session_id,
                status=STATUS_FAILED,
                message=_INTERRUPTED,
                created_at=job.created_at,
                started_at=job.started_at,
                finished_at=utc_now(),
                error=_INTERRUPTED,
            ),
        )


class MeasurementRunner:
    def __init__(self, settings: ApiSettings, estimator_factory: EstimatorFactory) -> None:
        self._settings = settings
        self._estimator_factory = estimator_factory
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._active = 0
        self._inflight_sessions: set[str] = set()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_pose_jobs,
            thread_name_prefix="measure",
        )
        mark_interrupted_measurements(settings.session_root)

    def submit(self, session: VerifiedSession) -> MeasurementJob:
        if report_path(session.session_dir).exists():
            raise DuplicateMeasurementError("A measurement report already exists. It was not overwritten.")
        job = MeasurementJob(
            job_id=secrets.token_hex(16),
            session_id=session.session_id,
            status=STATUS_QUEUED,
            message="Measurement is queued. This is not a 3D joint angle.",
            created_at=utc_now(),
            started_at=None,
            finished_at=None,
            error=None,
        )
        with self._lock:
            if session.session_id in self._inflight_sessions:
                raise DuplicateMeasurementError("A measurement is already running for this session.")
            current = load_measurement_job(session.session_dir)
            if current is not None and current.status in ACTIVE_STATUSES:
                raise DuplicateMeasurementError("A measurement is already running for this session.")
            if self._active >= self._settings.max_pose_jobs:
                raise MeasurementCapacityError("Measurement capacity is full.")
            save_measurement_job(session.session_dir, job)
            self._inflight_sessions.add(session.session_id)
            self._active += 1
        self._executor.submit(self._run, session.session_id, job.job_id)
        return job

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        with self._lock:
            return self._idle.wait_for(lambda: self._active == 0, timeout=timeout)

    def _run(self, session_id: str, job_id: str) -> None:
        session_dir: Path | None = None
        try:
            session = load_verified_session(self._settings.session_root, session_id)
            session_dir = session.session_dir
            job = load_measurement_job(session_dir)
            if job is None or job.job_id != job_id:
                return
            save_measurement_job(
                session_dir,
                MeasurementJob(
                    job_id=job.job_id,
                    session_id=job.session_id,
                    status=STATUS_RUNNING,
                    message="Measurement is running on manual FFC and Release frames.",
                    created_at=job.created_at,
                    started_at=utc_now(),
                    finished_at=None,
                    error=None,
                ),
            )
            self._execute(session, job)
        except (InvalidSessionId, SessionNotFound, SessionNotVerified, SessionStoreError):
            if session_dir is not None:
                self._fail(session_dir, job_id, "Session could not be verified.")
        except Exception:
            logger.exception("Measurement worker failed")
            if session_dir is not None:
                self._fail(session_dir, job_id, _FAILED)
        finally:
            with self._lock:
                self._inflight_sessions.discard(session_id)
                if self._active > 0:
                    self._active -= 1
                self._idle.notify_all()

    def _execute(self, session: VerifiedSession, job: MeasurementJob) -> None:
        root = measure_dir(session.session_dir)
        staging = root / STAGING_DIRNAME
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        output = staging / REPORT_NAME
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
            attempt = measure_manual_front_knee(
                session.video_path,
                session.session_dir / MANIFEST_NAME,
                labels_path(session.session_dir),
                output,
                confirm_label_link=True,
                estimator=estimator,
            )
            if not attempt.ok or attempt.output_path is None:
                self._fail(
                    session.session_dir,
                    job.job_id,
                    public_detail(attempt.message, _FAILED),
                )
                return
            destination = report_path(session.session_dir)
            if destination.exists():
                self._fail(session.session_dir, job.job_id, "A measurement report already exists. It was not overwritten.")
                return
            attempt.output_path.replace(destination)
            current = load_measurement_job(session.session_dir)
            if current is None or current.job_id != job.job_id:
                return
            save_measurement_job(
                session.session_dir,
                MeasurementJob(
                    job_id=job.job_id,
                    session_id=job.session_id,
                    status=STATUS_COMPLETED,
                    message="Measurement completed. Angles are raw 2D values, not validated accuracy.",
                    created_at=current.created_at,
                    started_at=current.started_at,
                    finished_at=utc_now(),
                    error=None,
                ),
            )
        except OSError:
            logger.exception("Measurement could not write its report")
            self._fail(session.session_dir, job.job_id, _FAILED)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _fail(self, session_dir: Path, job_id: str, message: str) -> None:
        current = load_measurement_job(session_dir)
        if current is None or current.job_id != job_id:
            return
        _discard_incomplete(measure_dir(session_dir))
        save_measurement_job(
            session_dir,
            MeasurementJob(
                job_id=current.job_id,
                session_id=current.session_id,
                status=STATUS_FAILED,
                message=message,
                created_at=current.created_at,
                started_at=current.started_at,
                finished_at=utc_now(),
                error=message,
            ),
        )


def get_measurement_runner() -> MeasurementRunner:
    global _runner
    with _runner_lock:
        if _runner is None:
            _runner = MeasurementRunner(get_settings(), get_estimator_factory())
        return _runner


def reset_measurement_runner() -> None:
    global _runner
    with _runner_lock:
        if _runner is not None:
            _runner.shutdown()
            _runner = None


def _job_from_payload(payload: dict[str, object]) -> MeasurementJob:
    job_id = payload.get("job_id")
    session_id = payload.get("session_id")
    status = payload.get("status")
    message = payload.get("message")
    created_at = payload.get("created_at")
    started_at = payload.get("started_at")
    finished_at = payload.get("finished_at")
    error = payload.get("error")
    if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
        raise MeasurementJobError("Invalid job record.")
    if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
        raise MeasurementJobError("Invalid job record.")
    if status not in {STATUS_QUEUED, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED}:
        raise MeasurementJobError("Invalid job record.")
    if not isinstance(message, str) or not message:
        raise MeasurementJobError("Invalid job record.")
    if not isinstance(created_at, str) or not created_at:
        raise MeasurementJobError("Invalid job record.")
    if started_at is not None and not isinstance(started_at, str):
        raise MeasurementJobError("Invalid job record.")
    if finished_at is not None and not isinstance(finished_at, str):
        raise MeasurementJobError("Invalid job record.")
    if error is not None and not isinstance(error, str):
        raise MeasurementJobError("Invalid job record.")
    return MeasurementJob(
        job_id=job_id,
        session_id=session_id,
        status=status,
        message=message,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
        error=error,
    )


def _discard_incomplete(root: Path) -> None:
    staging = root / STAGING_DIRNAME
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    report = root / REPORT_NAME
    job = None
    job_path = root / JOB_RECORD_NAME
    if job_path.is_file():
        try:
            payload = json.loads(job_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("status") == STATUS_COMPLETED:
                job = payload
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            job = None
    if job is None:
        report.unlink(missing_ok=True)
