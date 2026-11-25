"""Local API settings for session storage and upload limits.

These values configure the prototype HTTP layer. They do not change
inspection, hashing, or biomechanical calculations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_MAX_UPLOAD_BYTES = 80 * 1024 * 1024
_DEFAULT_MULTIPART_OVERHEAD_BYTES = 1024 * 1024
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SESSION_ROOT = _BACKEND_ROOT / "local_sessions"

_override: "ApiSettings | None" = None


_DEFAULT_MAX_POSE_JOBS = 1
_DEFAULT_MAX_REVIEW_FRAMES = 8
_DEFAULT_MAX_FRAME_DECODES = 1
# One side-on delivery. The stored demonstration clip is 223 frames,
# about 7.4 seconds at 30 fps. The recording protocol allows 60 fps.
# Thirty seconds at 60 fps is 1800 frames: one approach and delivery,
# not a multi-minute upload.
_DEFAULT_MAX_DECODED_FRAMES = 1800
_DEFAULT_MAX_DURATION_SECONDS = 30.0
_DEFAULT_TRUSTED_HOSTS = ("localhost", "127.0.0.1", "testserver", "::1")
_DEFAULT_UPLOAD_LIMIT = 40
_DEFAULT_JOB_LIMIT = 20
_DEFAULT_RATE_WINDOW_SECONDS = 600


@dataclass(frozen=True)
class ApiSettings:
    """Filesystem and size limits for delivery-session uploads."""

    session_root: Path
    max_upload_bytes: int
    multipart_overhead_bytes: int = _DEFAULT_MULTIPART_OVERHEAD_BYTES
    max_pose_jobs: int = _DEFAULT_MAX_POSE_JOBS
    max_review_frames: int = _DEFAULT_MAX_REVIEW_FRAMES
    max_frame_decodes: int = _DEFAULT_MAX_FRAME_DECODES
    max_decoded_frames: int = _DEFAULT_MAX_DECODED_FRAMES
    max_duration_seconds: float = _DEFAULT_MAX_DURATION_SECONDS
    trusted_hosts: tuple[str, ...] = _DEFAULT_TRUSTED_HOSTS
    rate_limit_enabled: bool = True
    upload_limit: int = _DEFAULT_UPLOAD_LIMIT
    job_limit: int = _DEFAULT_JOB_LIMIT
    rate_window_seconds: int = _DEFAULT_RATE_WINDOW_SECONDS

    @property
    def max_request_bytes(self) -> int:
        return self.max_upload_bytes + self.multipart_overhead_bytes


def load_settings() -> ApiSettings:
    """Read settings from the environment, or use local prototype defaults.

    A relative ``FAST_BOWLING_SESSION_ROOT`` is resolved from the backend
    directory, not the process working directory. The default path is the
    existing ``backend/local_sessions`` directory.
    """
    root_value = os.environ.get("FAST_BOWLING_SESSION_ROOT", "").strip()
    if root_value:
        session_root = Path(root_value)
        if not session_root.is_absolute():
            session_root = _BACKEND_ROOT / session_root
        session_root = session_root.resolve()
    else:
        session_root = _DEFAULT_SESSION_ROOT
    return ApiSettings(
        session_root=session_root,
        max_upload_bytes=_positive_int("FAST_BOWLING_MAX_UPLOAD_BYTES", _DEFAULT_MAX_UPLOAD_BYTES),
        max_pose_jobs=_positive_int("FAST_BOWLING_MAX_POSE_JOBS", _DEFAULT_MAX_POSE_JOBS),
        max_decoded_frames=_positive_int("FAST_BOWLING_MAX_DECODED_FRAMES", _DEFAULT_MAX_DECODED_FRAMES),
        max_duration_seconds=_positive_float(
            "FAST_BOWLING_MAX_DURATION_SECONDS",
            _DEFAULT_MAX_DURATION_SECONDS,
        ),
        trusted_hosts=_trusted_hosts(),
        rate_limit_enabled=_flag("FAST_BOWLING_RATE_LIMIT", True),
        upload_limit=_positive_int("FAST_BOWLING_UPLOAD_LIMIT", _DEFAULT_UPLOAD_LIMIT),
        job_limit=_positive_int("FAST_BOWLING_JOB_LIMIT", _DEFAULT_JOB_LIMIT),
        rate_window_seconds=_positive_int(
            "FAST_BOWLING_RATE_WINDOW_SECONDS",
            _DEFAULT_RATE_WINDOW_SECONDS,
        ),
    )


def ensure_session_storage(settings: ApiSettings) -> None:
    """Create the storage root if needed and fail clearly when it is not writable.

    Existing files in the directory are not deleted or rewritten.
    """
    root = settings.session_root
    probe = root / ".paceframe-write-probe"
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        raise RuntimeError(
            f"Session storage is not writable: {root}. "
            "Set FAST_BOWLING_SESSION_ROOT to a writable directory."
        ) from error


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer.") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0.")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number.") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0.")
    return value


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def _trusted_hosts() -> tuple[str, ...]:
    raw = os.environ.get("FAST_BOWLING_TRUSTED_HOSTS", "").strip()
    if not raw:
        return _DEFAULT_TRUSTED_HOSTS
    hosts = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    if not hosts or "*" in hosts:
        raise ValueError("FAST_BOWLING_TRUSTED_HOSTS must list host names and must not contain *.")
    return hosts


def get_settings() -> ApiSettings:
    """Return test overrides when set, otherwise load from the environment."""
    if _override is not None:
        return _override
    return load_settings()


def set_settings_override(settings: ApiSettings | None) -> None:
    """Replace settings for tests. Pass ``None`` to restore environment loading."""
    global _override
    _override = settings
