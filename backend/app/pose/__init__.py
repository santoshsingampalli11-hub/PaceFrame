"""Pose estimation. Independent of the web API.

Estimator-independent types are imported immediately. Video-loop helpers in
``estimator`` load on first use so ``PoseFrame`` can be imported without
OpenCV. Import the MediaPipe implementation explicitly from
``app.pose.mediapipe_estimator``.
"""

from app.pose.landmarks import LANDMARK_NAMES, SKELETON_CONNECTIONS, Landmark, PoseFrame

__all__ = [
    "LANDMARK_NAMES",
    "SKELETON_CONNECTIONS",
    "Landmark",
    "PoseEstimationError",
    "PoseEstimator",
    "PoseFrame",
    "estimate_video_poses",
    "validate_frame_image",
]

_ESTIMATOR_EXPORTS = {
    "PoseEstimationError",
    "PoseEstimator",
    "estimate_video_poses",
    "validate_frame_image",
}


def __getattr__(name: str):
    if name in _ESTIMATOR_EXPORTS:
        from app.pose import estimator as _estimator

        return getattr(_estimator, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
