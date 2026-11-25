"""2D front-knee angle at manually chosen FFC and Release frames.

Definition
    The front-knee angle is the unsigned image-plane angle hip → knee → ankle.
    The vertex is the knee. The result is in degrees, from 0 to 180.

    FRONT_HIP, FRONT_KNEE, and FRONT_ANKLE are the MediaPipe landmarks on the
    anatomical side the caller names as the front leg: ``left`` or ``right``.
    Left and right are the athlete's sides, not the sides of the picture.
    Screen position, horizontal motion, and handedness are not used.

Calculation
    Landmark ``x`` and ``y`` are normalized image coordinates. They are
    converted to pixels with the frame's width and height, the same scaling as
    ``PoseFrame.pixel_xy``, and then passed to ``angle_abc_degrees``.
    Normalized coordinates are not used directly: on a non-square image, x and
    y are different pixel scales, so an angle in that space is not the angle
    seen in the image.

    This is a projected 2D angle. It is not a laboratory 3D joint angle, not a
    technique score, and not an injury estimate. Visibility and presence are
    not treated as proof that the point is on the body.

Phases
    FFC and Release come from a manual ``PhaseLabel``. This module does not
    detect either event and does not call the experimental contact search.
    If the exact labeled frame is absent, a neighbor is not substituted.

Outside the image
    A finite coordinate slightly outside 0..1 can be a real MediaPipe output.
    It is not clamped. The angle is still calculated, and the result carries a
    warning that the point is not an in-frame observation.

Review status
    ``no_structural_warning`` means the three landmarks were present, finite,
    inside the image, and both model scores were supplied. It does not mean
    the pose is anatomically correct.
    ``review_required`` means an angle was calculated, but a person should look
    at a descriptive warning, such as a point outside the image or a missing
    visibility or presence score. A low score is not itself a warning. There
    is no visibility cutoff.
    ``unavailable`` means no angle was returned.

    Measurements use the raw MediaPipe landmarks on the pose frame. Manual foot
    corrections and experimental contact candidates are not read.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.annotations.models import PhaseLabel
from app.biomechanics.geometry import GeometryError, Point2D, angle_abc_degrees
from app.pose.landmarks import Landmark, PoseFrame

METRIC_NAME = "2d_front_knee_angle"
SOURCE = "raw_2d_mediapipe_landmarks"
REVIEW_CLEAR = "no_structural_warning"
REVIEW_REQUIRED = "review_required"
REVIEW_UNAVAILABLE = "unavailable"
EVIDENCE_SCHEMA_VERSION = "front-knee-evidence-v1"
CALCULATION_ID = "angle_abc_degrees"
ANGLE_DEFINITION = "unsigned interior hip-knee-ankle angle, vertex at the knee, degrees 0 to 180"
_LEGS = {"left", "right"}
_PHASES = {"FFC", "Release"}
_PARTS = ("hip", "knee", "ankle")


@dataclass(frozen=True)
class LandmarkEvidence:
    """What was known about one of the three raw landmarks used for the angle.

    ``visibility`` and ``presence`` are the model's own scores, or ``None``
    when the model did not supply them. They are not landmark accuracy.
    Coordinates are not copied here.
    """

    role: str
    name: str
    available: bool
    visibility: float | None
    presence: float | None
    outside_image: bool | None
    coordinates_finite: bool | None


@dataclass(frozen=True)
class LandmarkCalculationPoint:
    """One joint as it was passed into the angle function.

    Pixel values are the floating-point inputs. They are not rounded.
    Visibility and presence stay null when the model did not supply them.
    """

    role: str
    name: str
    x_normalized: float
    y_normalized: float
    x_px: float
    y_px: float
    visibility: float | None
    presence: float | None

    def to_json(self) -> dict[str, object]:
        return {
            "role": self.role,
            "name": self.name,
            "x_normalized": self.x_normalized,
            "y_normalized": self.y_normalized,
            "x_px": self.x_px,
            "y_px": self.y_px,
            "visibility": self.visibility,
            "presence": self.presence,
        }


@dataclass(frozen=True)
class FrontKneeCalculationEvidence:
    """Coordinates and provenance for one available angle.

    ``video_sha256`` is filled when the measurement report is written.
    The angle function does not know the file hash.
    """

    schema_version: str
    calculation: str
    definition: str
    frame_index: int
    frame_timestamp_seconds: float
    image_width_px: int
    image_height_px: int
    front_leg: str
    landmark_names: tuple[str, str, str]
    hip: LandmarkCalculationPoint
    knee: LandmarkCalculationPoint
    ankle: LandmarkCalculationPoint
    angle_degrees: float
    origin: str = "top_left"
    positive_x: str = "right"
    positive_y: str = "down"
    coordinate_unit: str = "image_pixels"
    video_sha256: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "calculation": self.calculation,
            "definition": self.definition,
            "frame_index": self.frame_index,
            "frame_timestamp_seconds": self.frame_timestamp_seconds,
            "image_width_px": self.image_width_px,
            "image_height_px": self.image_height_px,
            "front_leg": self.front_leg,
            "landmark_names": list(self.landmark_names),
            "hip": self.hip.to_json(),
            "knee": self.knee.to_json(),
            "ankle": self.ankle.to_json(),
            "angle_degrees": self.angle_degrees,
            "origin": self.origin,
            "positive_x": self.positive_x,
            "positive_y": self.positive_y,
            "coordinate_unit": self.coordinate_unit,
            "video_sha256": self.video_sha256,
        }


@dataclass(frozen=True)
class FrontKneeAngle:
    """One phase's front-knee angle, or an explicit reason it was not calculated.

    ``angle_degrees`` is ``None`` when ``status`` is ``unavailable``.
    ``review_status`` describes the result. ``no_structural_warning`` is not
    proof that the angle is anatomically correct. ``warnings`` stay attached
    when the angle cannot be calculated.
    """

    metric: str
    phase: str
    frame_index: int | None
    front_leg: str | None
    angle_degrees: float | None
    status: str
    reason: str
    source: str
    warnings: tuple[str, ...] = ()
    evidence: tuple[LandmarkEvidence, ...] = ()
    review_status: str = REVIEW_UNAVAILABLE
    calculation_evidence: FrontKneeCalculationEvidence | None = None

    def __post_init__(self) -> None:
        if self.metric != METRIC_NAME:
            raise ValueError(f"metric must be {METRIC_NAME!r}.")
        if self.source != SOURCE:
            raise ValueError(f"source must be {SOURCE!r}.")
        if self.status == "available":
            angle = self.angle_degrees
            if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle):
                raise ValueError("An available front-knee angle must be a finite number.")
            if not 0.0 <= float(angle) <= 180.0:
                raise ValueError(f"An available front-knee angle must be in 0..180, got {angle!r}.")
            if self.reason:
                raise ValueError("An available front-knee angle must not carry an unavailable reason.")
            expected = REVIEW_REQUIRED if self.warnings else REVIEW_CLEAR
            if self.review_status != expected:
                raise ValueError(f"review_status must be {expected!r} for this available result.")
            return
        if self.status != "unavailable":
            raise ValueError(f"status must be 'available' or 'unavailable', got {self.status!r}.")
        if self.angle_degrees is not None:
            raise ValueError("An unavailable front-knee result must not contain an angle.")
        if not self.reason:
            raise ValueError("An unavailable front-knee result must explain why.")
        if self.review_status != REVIEW_UNAVAILABLE:
            raise ValueError("An unavailable front-knee result must use review_status 'unavailable'.")


def front_knee_angle(frame: PoseFrame, front_leg: str, phase: str) -> FrontKneeAngle:
    """Return the front-knee angle on one pose frame.

    The original ``PoseFrame`` and its landmarks are not modified. A missing
    point is not invented. Foot corrections are not read.
    """
    leg = front_leg if front_leg in _LEGS else None
    if phase not in _PHASES:
        return _unavailable(phase, None, leg, f"Phase must be FFC or Release, got {phase!r}.")
    if not _valid_index(frame.frame_index):
        return _unavailable(phase, None, leg, f"Frame index must be an integer >= 0, got {frame.frame_index!r}.")
    if leg is None:
        return _unavailable(
            phase,
            frame.frame_index,
            None,
            "Front leg must be the athlete's 'left' or 'right'. No side was inferred.",
        )
    if not _valid_size(frame.image_width, frame.image_height):
        return _unavailable(
            phase,
            frame.frame_index,
            leg,
            f"Frame {frame.frame_index} has invalid image size {frame.image_width}x{frame.image_height}.",
        )

    evidence, warnings, points = _inspect_leg(frame, leg)
    if not frame.pose_detected:
        return _unavailable(phase, frame.frame_index, leg, f"No pose was detected on frame {frame.frame_index}.", warnings, evidence)
    missing = [item.name for item in evidence if not item.available]
    if missing:
        listed = ", ".join(missing)
        verb = "is" if len(missing) == 1 else "are"
        return _unavailable(
            phase,
            frame.frame_index,
            leg,
            f"{listed} {verb} missing on frame {frame.frame_index}. It was not invented.",
            warnings,
            evidence,
        )
    non_finite = [item.name for item in evidence if item.coordinates_finite is False]
    if non_finite:
        return _unavailable(
            phase,
            frame.frame_index,
            leg,
            f"{non_finite[0]} on frame {frame.frame_index} has a non-finite coordinate.",
            warnings,
            evidence,
        )

    hip_px = _pixel_point(points["hip"], frame.image_width, frame.image_height)
    knee_px = _pixel_point(points["knee"], frame.image_width, frame.image_height)
    ankle_px = _pixel_point(points["ankle"], frame.image_width, frame.image_height)
    try:
        angle = angle_abc_degrees(hip_px, knee_px, ankle_px)
    except GeometryError as error:
        return _unavailable(phase, frame.frame_index, leg, str(error), warnings, evidence)
    calculation = _calculation_evidence(
        frame,
        leg,
        points,
        {"hip": hip_px, "knee": knee_px, "ankle": ankle_px},
        angle,
    )
    return _available(phase, frame.frame_index, leg, angle, warnings, evidence, calculation)


def front_knee_angles_at_manual_phases(
    frames: Sequence[PoseFrame],
    label: PhaseLabel,
    front_leg: str,
) -> tuple[FrontKneeAngle, FrontKneeAngle]:
    """Measure FFC and Release on the exact manual frames.

    Does not detect events and does not use a nearby frame when the labeled
    index is missing. The sequence is read once, so a one-pass iterable is not
    mistaken for a missing frame. Does not modify ``label`` or the pose frames.
    """
    sequence = tuple(frames)
    sequence_problem = _sequence_problem(sequence)
    return (
        _at_phase(sequence, label.ffc_frame, "FFC", front_leg, sequence_problem),
        _at_phase(sequence, label.release_frame, "Release", front_leg, sequence_problem),
    )


def _at_phase(
    frames: Sequence[PoseFrame],
    frame_index: int | None,
    phase: str,
    front_leg: str,
    sequence_problem: str | None,
) -> FrontKneeAngle:
    leg = front_leg if front_leg in _LEGS else None
    if frame_index is None:
        return _unavailable(phase, None, leg, f"{phase} was not annotated. No angle was calculated.")
    if not _valid_index(frame_index):
        return _unavailable(phase, None, leg, f"{phase} frame must be an integer >= 0, got {frame_index!r}.")
    if sequence_problem is not None:
        return _unavailable(phase, frame_index, leg, sequence_problem)
    if leg is None:
        return _unavailable(
            phase,
            frame_index,
            None,
            "Front leg must be the athlete's 'left' or 'right'. No side was inferred.",
        )
    matches = [frame for frame in frames if frame.frame_index == frame_index]
    if not matches:
        return _unavailable(
            phase,
            frame_index,
            leg,
            f"Pose frame {frame_index} is not in the sequence. A neighboring frame was not used.",
        )
    return front_knee_angle(matches[0], leg, phase)


def _sequence_problem(frames: Sequence[PoseFrame]) -> str | None:
    if not frames:
        return "No pose frames were supplied."
    seen: set[int] = set()
    for frame in frames:
        index = frame.frame_index
        if not _valid_index(index):
            return f"Pose sequence has an invalid frame index {index!r}. No angle was calculated."
        if index in seen:
            return f"Pose sequence repeats frame index {index}. No angle was calculated."
        seen.add(index)
    return None


def _valid_index(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _valid_size(width: object, height: object) -> bool:
    return (
        not isinstance(width, bool)
        and not isinstance(height, bool)
        and isinstance(width, int)
        and isinstance(height, int)
        and width > 0
        and height > 0
    )


def _outside_image(landmark: Landmark) -> bool:
    return not (0.0 <= landmark.x <= 1.0 and 0.0 <= landmark.y <= 1.0)


def _inspect_leg(
    frame: PoseFrame,
    leg: str,
) -> tuple[tuple[LandmarkEvidence, ...], tuple[str, ...], dict[str, Landmark]]:
    evidence: list[LandmarkEvidence] = []
    warnings: list[str] = []
    points: dict[str, Landmark] = {}
    for part in _PARTS:
        name = f"{leg}_{part}"
        landmark = frame.landmarks.get(name) if frame.pose_detected else None
        if landmark is None:
            evidence.append(
                LandmarkEvidence(part, name, False, None, None, None, None)
            )
            continue
        finite = math.isfinite(landmark.x) and math.isfinite(landmark.y)
        outside = _outside_image(landmark) if finite else None
        evidence.append(
            LandmarkEvidence(
                part,
                name,
                True,
                landmark.visibility,
                landmark.presence,
                outside,
                finite,
            )
        )
        points[part] = landmark
        if finite and outside:
            warnings.append(
                f"{name} is outside normalized image bounds "
                f"(x={landmark.x!r}, y={landmark.y!r}). It was not clamped and is not an in-frame observation."
            )
        if landmark.visibility is None or landmark.presence is None:
            missing_scores = []
            if landmark.visibility is None:
                missing_scores.append("visibility")
            if landmark.presence is None:
                missing_scores.append("presence")
            warnings.append(
                f"{name} has no {' or '.join(missing_scores)} score. "
                "A missing score is not landmark accuracy, and no cutoff was applied."
            )
    return tuple(evidence), tuple(warnings), points


def _review_status(status: str, warnings: tuple[str, ...]) -> str:
    if status != "available":
        return REVIEW_UNAVAILABLE
    if warnings:
        return REVIEW_REQUIRED
    return REVIEW_CLEAR


def _available(
    phase: str,
    frame_index: int,
    front_leg: str,
    angle: float,
    warnings: tuple[str, ...],
    evidence: tuple[LandmarkEvidence, ...],
    calculation_evidence: FrontKneeCalculationEvidence,
) -> FrontKneeAngle:
    return FrontKneeAngle(
        metric=METRIC_NAME,
        phase=phase,
        frame_index=frame_index,
        front_leg=front_leg,
        angle_degrees=angle,
        status="available",
        reason="",
        source=SOURCE,
        warnings=warnings,
        evidence=evidence,
        review_status=_review_status("available", warnings),
        calculation_evidence=calculation_evidence,
    )


def _calculation_evidence(
    frame: PoseFrame,
    leg: str,
    points: dict[str, Landmark],
    pixels: dict[str, Point2D],
    angle: float,
) -> FrontKneeCalculationEvidence:
    hip_name = f"{leg}_hip"
    knee_name = f"{leg}_knee"
    ankle_name = f"{leg}_ankle"
    return FrontKneeCalculationEvidence(
        EVIDENCE_SCHEMA_VERSION,
        CALCULATION_ID,
        ANGLE_DEFINITION,
        frame.frame_index,
        frame.timestamp_seconds,
        frame.image_width,
        frame.image_height,
        leg,
        (hip_name, knee_name, ankle_name),
        _point("hip", hip_name, points["hip"], pixels["hip"]),
        _point("knee", knee_name, points["knee"], pixels["knee"]),
        _point("ankle", ankle_name, points["ankle"], pixels["ankle"]),
        angle,
    )


def _point(role: str, name: str, landmark: Landmark, pixel: Point2D) -> LandmarkCalculationPoint:
    return LandmarkCalculationPoint(
        role,
        name,
        landmark.x,
        landmark.y,
        pixel.x,
        pixel.y,
        landmark.visibility,
        landmark.presence,
    )


def _pixel_point(landmark: Landmark, width: int, height: int) -> Point2D:
    return Point2D(landmark.x * width, landmark.y * height)


def _unavailable(
    phase: str,
    frame_index: int | None,
    front_leg: str | None,
    reason: str,
    warnings: tuple[str, ...] = (),
    evidence: tuple[LandmarkEvidence, ...] = (),
) -> FrontKneeAngle:
    return FrontKneeAngle(
        metric=METRIC_NAME,
        phase=phase,
        frame_index=frame_index,
        front_leg=front_leg,
        angle_degrees=None,
        status="unavailable",
        reason=reason,
        source=SOURCE,
        warnings=warnings,
        evidence=evidence,
        review_status=REVIEW_UNAVAILABLE,
    )
