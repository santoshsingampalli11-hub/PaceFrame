"""Quality diagnostics from a sequence of generic ``PoseFrame`` results.

These numbers describe what the pose estimator produced. They are not
measurement accuracy, not a video accept/reject decision, and not bowling
technique or injury scores.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from app.biomechanics.geometry import Point2D, distance
from app.pose.landmarks import LANDMARK_NAMES, PoseFrame

_HIP_NAMES = ("left_hip", "right_hip")


class QualityDiagnosticsError(ValueError):
    """The pose sequence cannot be summarised."""


@dataclass(frozen=True)
class LandmarkSignalSummary:
    """Estimator visibility/presence for one landmark name across detected poses.

    ``mean_visibility`` and ``mean_presence`` are averages of the model's own
    scores where they were provided. They are not landmark accuracy.
    """

    name: str
    frames_with_landmark: int
    visibility_count: int
    mean_visibility: float | None
    presence_count: int
    mean_presence: float | None


@dataclass(frozen=True)
class HipCentreMotion:
    """Normalized 2D image-coordinate displacement of the hip centre.

    On each frame with both hips:

        hip_center_x = (left_hip.x + right_hip.x) / 2
        hip_center_y = (left_hip.y + right_hip.y) / 2

    ``x`` and ``y`` are the landmark image-normalized coordinates (fraction of
    image width and height). They are image-space coordinates, not metres.

    Between two consecutive sequence frames that both have a valid hip centre:

        movement = hypot(current_x - previous_x, current_y - previous_y)

    That quantity is a normalized 2D image-coordinate displacement. It is not
    physical athlete displacement, centre of mass, stride, velocity, or
    measurement accuracy. Pixel conversion is not used, so the value does not
    depend on image resolution or portrait vs landscape pixel aspect.

    Pairs are adjacent items in the given sequence only. Missing poses, missing
    hips, and other gaps are not bridged.
    """

    pair_count: int
    mean_normalized_displacement: float | None
    median_normalized_displacement: float | None
    max_normalized_displacement: float | None


@dataclass(frozen=True)
class QualityDiagnostics:
    """Summary of pose coverage and tracking stability for one sequence.

    ``pose_coverage`` is ``frames_with_pose / frame_count``. Detection is not
    accuracy. This object has no pass/fail or accept/reject field.
    """

    frame_count: int
    frames_with_pose: int
    pose_coverage: float
    longest_run_without_pose: int
    missing_pose_run_count: int
    landmark_signals: tuple[LandmarkSignalSummary, ...]
    hip_centre_motion: HipCentreMotion


def diagnose_pose_frames(frames: Sequence[PoseFrame]) -> QualityDiagnostics:
    """Return diagnostics for every frame in ``frames``, in the given order.

    ``frames`` should be the full decoded sequence (including frames with no
    pose). The result describes this sequence only; it does not judge whether
    the video is suitable for biomechanics.
    """
    if not frames:
        raise QualityDiagnosticsError("Cannot compute diagnostics for an empty pose sequence.")

    _require_ordered_consistent_frames(frames)

    detected = [frame.pose_detected for frame in frames]
    frames_with_pose = sum(detected)
    longest_run, run_count = _missing_pose_runs(detected)

    return QualityDiagnostics(
        frame_count=len(frames),
        frames_with_pose=frames_with_pose,
        pose_coverage=frames_with_pose / len(frames),
        longest_run_without_pose=longest_run,
        missing_pose_run_count=run_count,
        landmark_signals=_landmark_signals(frames),
        hip_centre_motion=_hip_centre_motion(frames),
    )


def _require_ordered_consistent_frames(frames: Sequence[PoseFrame]) -> None:
    previous_index: int | None = None
    expected_size: tuple[int, int] | None = None
    for frame in frames:
        if frame.image_width <= 0 or frame.image_height <= 0:
            raise QualityDiagnosticsError(
                f"Frame {frame.frame_index} has invalid image size "
                f"{frame.image_width}x{frame.image_height}."
            )
        size = (frame.image_width, frame.image_height)
        if expected_size is None:
            expected_size = size
        elif size != expected_size:
            raise QualityDiagnosticsError(
                "All frames in a diagnostic sequence must share the same image size."
            )
        if previous_index is not None and frame.frame_index <= previous_index:
            raise QualityDiagnosticsError(
                "Pose frames must be in strictly increasing frame_index order."
            )
        previous_index = frame.frame_index


def _missing_pose_runs(detected: Sequence[bool]) -> tuple[int, int]:
    longest = 0
    run_count = 0
    current = 0
    for has_pose in detected:
        if has_pose:
            if current > 0:
                run_count += 1
                longest = max(longest, current)
                current = 0
        else:
            current += 1
    if current > 0:
        run_count += 1
        longest = max(longest, current)
    return longest, run_count


def _landmark_signals(frames: Sequence[PoseFrame]) -> tuple[LandmarkSignalSummary, ...]:
    visibilities: dict[str, list[float]] = {name: [] for name in LANDMARK_NAMES}
    presences: dict[str, list[float]] = {name: [] for name in LANDMARK_NAMES}
    counts = {name: 0 for name in LANDMARK_NAMES}

    for frame in frames:
        if not frame.pose_detected:
            continue
        for name in LANDMARK_NAMES:
            landmark = frame.landmarks.get(name)
            if landmark is None:
                continue
            counts[name] += 1
            if landmark.visibility is not None:
                visibilities[name].append(landmark.visibility)
            if landmark.presence is not None:
                presences[name].append(landmark.presence)

    return tuple(
        LandmarkSignalSummary(
            name=name,
            frames_with_landmark=counts[name],
            visibility_count=len(visibilities[name]),
            mean_visibility=_mean_or_none(visibilities[name]),
            presence_count=len(presences[name]),
            mean_presence=_mean_or_none(presences[name]),
        )
        for name in LANDMARK_NAMES
    )


def _hip_centre_motion(frames: Sequence[PoseFrame]) -> HipCentreMotion:
    displacements: list[float] = []
    previous_centre: Point2D | None = None
    previous_valid = False

    for frame in frames:
        centre = _hip_centre_normalized(frame) if frame.pose_detected else None
        if previous_valid and previous_centre is not None and centre is not None:
            displacements.append(distance(previous_centre, centre))
        previous_centre = centre
        previous_valid = frame.pose_detected and centre is not None

    if not displacements:
        return HipCentreMotion(
            pair_count=0,
            mean_normalized_displacement=None,
            median_normalized_displacement=None,
            max_normalized_displacement=None,
        )
    return HipCentreMotion(
        pair_count=len(displacements),
        mean_normalized_displacement=statistics.fmean(displacements),
        median_normalized_displacement=statistics.median(displacements),
        max_normalized_displacement=max(displacements),
    )


def _hip_centre_normalized(frame: PoseFrame) -> Point2D | None:
    if any(name not in frame.landmarks for name in _HIP_NAMES):
        return None
    left = frame.landmarks["left_hip"]
    right = frame.landmarks["right_hip"]
    return Point2D((left.x + right.x) / 2.0, (left.y + right.y) / 2.0)


def _mean_or_none(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return statistics.fmean(values)
