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
from app.quality.temporal import (
    ContinuityNotes,
    LandmarkDeviation,
    LandmarkStep,
    continuity_notes,
    exploratory_large_steps,
    landmark_deviations,
    landmark_steps,
)

__all__ = [
    "ContinuityNotes",
    "HipCentreMotion",
    "LandmarkDeviation",
    "LandmarkSignalSummary",
    "LandmarkStep",
    "QualityDiagnostics",
    "QualityDiagnosticsError",
    "continuity_notes",
    "diagnose_pose_frames",
    "exploratory_large_steps",
    "landmark_deviations",
    "landmark_steps",
]
