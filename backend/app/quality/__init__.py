"""Pose-sequence quality diagnostics. Independent of MediaPipe and FastAPI.

This package summarises existing ``PoseFrame`` results. It does not accept or
reject videos, and it does not compute bowling metrics.
"""

from app.quality.diagnostics import (
    HipCentreMotion,
    LandmarkSignalSummary,
    QualityDiagnostics,
    QualityDiagnosticsError,
    diagnose_pose_frames,
)

__all__ = [
    "HipCentreMotion",
    "LandmarkSignalSummary",
    "QualityDiagnostics",
    "QualityDiagnosticsError",
    "diagnose_pose_frames",
]
