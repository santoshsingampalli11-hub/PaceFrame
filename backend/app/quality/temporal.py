"""Frame-to-frame landmark descriptions in normalized image coordinates.

Displacements use landmark ``x`` and ``y`` directly:

    movement = hypot(x1 - x0, y1 - y0)

They are fractions of the image, not metres, pixels, velocity, or acceleration.
A missing landmark is not bridged. A large value is not automatically a
tracking error, because a bowling action really does move quickly.
These numbers do not identify which person was tracked.

Frame indices must strictly increase. A gap, such as frame 0 then frame 2,
is allowed and is not treated as a consecutive step. A duplicate or a reversal
is rejected.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.biomechanics.geometry import Point2D, distance
from app.pose.landmarks import PoseFrame

TEMPORAL_LANDMARKS: tuple[str, ...] = (
    "left_shoulder",
    "right_shoulder",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
    "left_wrist",
    "right_wrist",
)


class TemporalSequenceError(ValueError):
    """Frame indices are duplicated or not in increasing order."""


@dataclass(frozen=True)
class LandmarkStep:
    """One adjacent-frame displacement of one landmark."""

    name: str
    from_frame: int
    to_frame: int
    normalized_displacement: float


@dataclass(frozen=True)
class LandmarkDeviation:
    """Distance from a middle sample to the chord between its neighbors.

    For normalized points P0, P1, P2 on three frame indices that increase by 1:

        deviation = distance(P1, (P0 + P2) / 2)

    A straight constant-speed path has deviation 0. A spike that returns is
    large. Fast real motion along a straight image path is not, by itself,
    a large deviation. This is not a clinical jitter score.
    """

    name: str
    frame_index: int
    normalized_deviation: float


@dataclass(frozen=True)
class ContinuityNotes:
    """Descriptive continuity facts. Not an identity decision."""

    missing_pose_frame_indices: tuple[int, ...]
    largest_steps: tuple[LandmarkStep, ...]
    note: str = (
        "Continuity indicators do not identify the bowler and do not correct landmarks."
    )


def landmark_steps(frames: Sequence[PoseFrame]) -> tuple[LandmarkStep, ...]:
    """Return displacements only between adjacent frames that both have the point."""
    _require_increasing(frames)
    steps: list[LandmarkStep] = []
    for earlier, later in zip(frames, frames[1:]):
        if later.frame_index - earlier.frame_index != 1:
            continue
        if not earlier.pose_detected or not later.pose_detected:
            continue
        for name in TEMPORAL_LANDMARKS:
            if name not in earlier.landmarks or name not in later.landmarks:
                continue
            start = earlier.landmarks[name]
            end = later.landmarks[name]
            steps.append(
                LandmarkStep(
                    name=name,
                    from_frame=earlier.frame_index,
                    to_frame=later.frame_index,
                    normalized_displacement=distance(
                        Point2D(start.x, start.y), Point2D(end.x, end.y)
                    ),
                )
            )
    return tuple(steps)


def landmark_deviations(frames: Sequence[PoseFrame]) -> tuple[LandmarkDeviation, ...]:
    """Local chord deviations. Gaps of missing pose or frame index are skipped."""
    _require_increasing(frames)
    deviations: list[LandmarkDeviation] = []
    for index in range(1, len(frames) - 1):
        previous, middle, following = frames[index - 1], frames[index], frames[index + 1]
        if middle.frame_index - previous.frame_index != 1:
            continue
        if following.frame_index - middle.frame_index != 1:
            continue
        if not (previous.pose_detected and middle.pose_detected and following.pose_detected):
            continue
        for name in TEMPORAL_LANDMARKS:
            if (
                name not in previous.landmarks
                or name not in middle.landmarks
                or name not in following.landmarks
            ):
                continue
            point_0 = previous.landmarks[name]
            point_1 = middle.landmarks[name]
            point_2 = following.landmarks[name]
            midpoint = Point2D((point_0.x + point_2.x) / 2.0, (point_0.y + point_2.y) / 2.0)
            deviations.append(
                LandmarkDeviation(
                    name=name,
                    frame_index=middle.frame_index,
                    normalized_deviation=distance(Point2D(point_1.x, point_1.y), midpoint),
                )
            )
    return tuple(deviations)


def largest_steps(steps: Sequence[LandmarkStep]) -> tuple[LandmarkStep, ...]:
    """One largest step per landmark name. Ties keep the earliest pair."""
    best: dict[str, LandmarkStep] = {}
    for step in steps:
        current = best.get(step.name)
        if current is None or step.normalized_displacement > current.normalized_displacement:
            best[step.name] = step
    return tuple(best[name] for name in TEMPORAL_LANDMARKS if name in best)


def exploratory_large_steps(
    steps: Sequence[LandmarkStep],
    normalized_limit: float | None,
) -> tuple[LandmarkStep, ...]:
    """Optional listing of steps at or above a caller-supplied limit.

    ``None`` disables the listing. Any limit is exploratory. It is not a
    validated tracking-error threshold. Booleans, NaN, infinity, and negative
    limits are rejected.
    """
    _require_optional_limit(normalized_limit)
    if normalized_limit is None:
        return ()
    return tuple(step for step in steps if step.normalized_displacement >= normalized_limit)


def continuity_notes(frames: Sequence[PoseFrame]) -> ContinuityNotes:
    """Summarise gaps and the largest observed image-space steps."""
    _require_increasing(frames)
    missing = tuple(frame.frame_index for frame in frames if not frame.pose_detected)
    return ContinuityNotes(
        missing_pose_frame_indices=missing,
        largest_steps=largest_steps(landmark_steps(frames)),
    )


def _require_increasing(frames: Sequence[PoseFrame]) -> None:
    for earlier, later in zip(frames, frames[1:]):
        if later.frame_index <= earlier.frame_index:
            raise TemporalSequenceError(
                "Pose frames must be in strictly increasing frame_index order. "
                f"Got {earlier.frame_index} then {later.frame_index}."
            )


def _require_optional_limit(value: float | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TemporalSequenceError(f"Exploratory limit must be a non-negative number or None, got {value!r}.")
    if value != value or value == float("inf") or value < 0:
        raise TemporalSequenceError(f"Exploratory limit must be finite and >= 0, got {value!r}.")
