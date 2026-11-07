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


@dataclass(frozen=True)
class ApiSettings:
    """Filesystem and size limits for delivery-session uploads."""

    session_root: Path
    max_upload_bytes: int
    multipart_overhead_bytes: int = _DEFAULT_MULTIPART_OVERHEAD_BYTES
    max_pose_jobs: int = _DEFAULT_MAX_POSE_JOBS
    max_review_frames: int = _DEFAULT_MAX_REVIEW_FRAMES
    max_frame_decodes: int = _DEFAULT_MAX_FRAME_DECODES

    @property
    def max_request_bytes(self) -> int:
        return self.max_upload_bytes + self.multipart_overhead_bytes


def load_settings() -> ApiSettings:
    """Read settings from the environment, or use local prototype defaults."""
    root_value = os.environ.get("FAST_BOWLING_SESSION_ROOT", "").strip()
    session_root = Path(root_value) if root_value else _DEFAULT_SESSION_ROOT
    max_value = os.environ.get("FAST_BOWLING_MAX_UPLOAD_BYTES", "").strip()
    if max_value:
        try:
            max_upload_bytes = int(max_value)
        except ValueError as error:
            raise ValueError("FAST_BOWLING_MAX_UPLOAD_BYTES must be an integer.") from error
    else:
        max_upload_bytes = _DEFAULT_MAX_UPLOAD_BYTES
    if max_upload_bytes <= 0:
        raise ValueError("FAST_BOWLING_MAX_UPLOAD_BYTES must be greater than 0.")
    jobs_value = os.environ.get("FAST_BOWLING_MAX_POSE_JOBS", "").strip()
    if jobs_value:
        try:
            max_pose_jobs = int(jobs_value)
        except ValueError as error:
            raise ValueError("FAST_BOWLING_MAX_POSE_JOBS must be an integer.") from error
    else:
        max_pose_jobs = _DEFAULT_MAX_POSE_JOBS
    if max_pose_jobs <= 0:
        raise ValueError("FAST_BOWLING_MAX_POSE_JOBS must be greater than 0.")
    return ApiSettings(
        session_root=session_root,
        max_upload_bytes=max_upload_bytes,
        max_pose_jobs=max_pose_jobs,
    )


def get_settings() -> ApiSettings:
    """Return test overrides when set, otherwise load from the environment."""
    if _override is not None:
        return _override
    return load_settings()


def set_settings_override(settings: ApiSettings | None) -> None:
    """Replace settings for tests. Pass ``None`` to restore environment loading."""
    global _override
    _override = settings
