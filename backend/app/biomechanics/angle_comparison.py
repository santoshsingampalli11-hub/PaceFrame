"""Compare a raw 2D front-knee angle with a manual reference angle.

The reference is an independently reviewed number in degrees. It is not
laboratory ground truth. Signed error is the automatic angle minus that
reference. A missing angle is not stored as zero.

Identity is supplied by the caller. ``FrontKneeAngle`` does not carry a
bowler or delivery id, and this module does not invent one. A comparison is
not accepted on phase alone: bowler, delivery, phase, frame index, and
anatomical front leg must all match.

``review_status`` and ``warnings`` are copied from the measurement. A result
with ``no_structural_warning`` is not an accuracy grade.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.biomechanics.front_knee import SOURCE, FrontKneeAngle

_PHASES = {"FFC", "Release"}
_LEGS = {"left", "right"}
_MANUAL = "manual"


class AngleComparisonError(ValueError):
    """A reference angle or comparison input cannot be interpreted."""


@dataclass(frozen=True)
class ManualAngleReference:
    """One manually reviewed front-knee angle. Not laboratory ground truth."""

    bowler_id: str
    delivery_id: str
    phase: str
    frame_index: int
    front_leg: str
    reference_angle_degrees: float
    reference_source: str = _MANUAL

    def __post_init__(self) -> None:
        object.__setattr__(self, "bowler_id", _required_id("bowler_id", self.bowler_id))
        object.__setattr__(self, "delivery_id", _required_id("delivery_id", self.delivery_id))
        if self.phase not in _PHASES:
            raise AngleComparisonError(f"phase must be 'FFC' or 'Release', got {self.phase!r}.")
        if isinstance(self.frame_index, bool) or not isinstance(self.frame_index, int) or self.frame_index < 0:
            raise AngleComparisonError(f"frame_index must be an integer >= 0, got {self.frame_index!r}.")
        if self.front_leg not in _LEGS:
            raise AngleComparisonError(f"front_leg must be 'left' or 'right', got {self.front_leg!r}.")
        _require_angle("reference_angle_degrees", self.reference_angle_degrees)
        if self.reference_source != _MANUAL:
            raise AngleComparisonError("reference_source must be 'manual'. This is not laboratory ground truth.")


@dataclass(frozen=True)
class FrontKneeAngleComparison:
    """One attempted comparison. Error fields are ``None`` unless status is ``compared``."""

    bowler_id: str
    delivery_id: str
    phase: str
    frame_index: int | None
    front_leg: str | None
    automatic_angle_degrees: float | None
    reference_angle_degrees: float | None
    signed_error_degrees: float | None
    absolute_error_degrees: float | None
    status: str
    reason: str
    review_status: str
    warnings: tuple[str, ...]
    measurement_source: str
    reference_source: str | None


@dataclass(frozen=True)
class PhaseAngleErrorSummary:
    """Errors for one phase. Statistics use valid pairs only.

    ``pair_count`` is the denominator. It is zero when no pair was compared,
    and the error fields are then ``None``, not zero degrees.
    """

    phase: str
    pair_count: int
    mean_signed_error_degrees: float | None
    mean_absolute_error_degrees: float | None
    max_absolute_error_degrees: float | None


@dataclass(frozen=True)
class AngleComparisonSummary:
    """Counts for every requested row. FFC and Release errors stay separate."""

    requested: int
    compared: int
    reference_missing: int
    measurement_unavailable: int
    mismatches: int
    duplicate_identity_rows: int
    ffc: PhaseAngleErrorSummary
    release: PhaseAngleErrorSummary


def compare_front_knee_angle(
    measurement: FrontKneeAngle,
    reference: ManualAngleReference | None,
    bowler_id: str,
    delivery_id: str,
) -> FrontKneeAngleComparison:
    """Compare one measurement with one manual reference for an explicit delivery.

    The measurement and the reference are not modified. Foot corrections and
    experimental contact frames are not read.

    ``bowler_id`` and ``delivery_id`` are the caller's context. They are checked
    against the reference only. This function does not inspect which video
    produced the pose. A later dataset workflow must attach the measurement to
    a verified source delivery before these errors are treated as dataset results.
    Repeated rows with the same bowler, delivery, phase, frame, and front leg are
    not averaged. See ``summarise_angle_comparisons``.
    """
    context_bowler = _required_id("bowler_id", bowler_id)
    context_delivery = _required_id("delivery_id", delivery_id)
    _assert_measurement_source(measurement)
    if reference is None:
        return _result(
            measurement,
            context_bowler,
            context_delivery,
            None,
            None,
            "reference_missing",
            "No manual reference angle. The comparison is not a zero error.",
        )
    if reference.bowler_id != context_bowler:
        return _result(
            measurement,
            context_bowler,
            context_delivery,
            reference,
            None,
            "mismatch",
            "Bowler id does not match. No angle error was calculated.",
        )
    if reference.delivery_id != context_delivery:
        return _result(
            measurement,
            context_bowler,
            context_delivery,
            reference,
            None,
            "mismatch",
            "Delivery id does not match. No angle error was calculated.",
        )
    if reference.phase != measurement.phase:
        return _result(
            measurement,
            context_bowler,
            context_delivery,
            reference,
            None,
            "mismatch",
            "Phase does not match. No angle error was calculated.",
        )
    if reference.frame_index != measurement.frame_index:
        return _result(
            measurement,
            context_bowler,
            context_delivery,
            reference,
            None,
            "mismatch",
            "Frame index does not match. No angle error was calculated.",
        )
    if reference.front_leg != measurement.front_leg:
        return _result(
            measurement,
            context_bowler,
            context_delivery,
            reference,
            None,
            "mismatch",
            "Front leg does not match. No angle error was calculated.",
        )
    if measurement.status != "available" or measurement.angle_degrees is None:
        return _result(
            measurement,
            context_bowler,
            context_delivery,
            reference,
            None,
            "unavailable",
            "Automatic measurement is unavailable. The comparison is an abstention, not a zero error. "
            + measurement.reason,
        )
    if not _angle_ok(reference.reference_angle_degrees):
        return _result(
            measurement,
            context_bowler,
            context_delivery,
            reference,
            None,
            "unavailable",
            "Reference angle is not a finite value in 0..180 degrees. No error was calculated.",
        )
    signed = float(measurement.angle_degrees) - float(reference.reference_angle_degrees)
    return _result(
        measurement,
        context_bowler,
        context_delivery,
        reference,
        signed,
        "compared",
        "Signed error is the automatic angle minus the manual reference. "
        "The reference is not laboratory ground truth. "
        "review_status is not an accuracy grade.",
    )


def summarise_angle_comparisons(rows: Sequence[FrontKneeAngleComparison]) -> AngleComparisonSummary:
    """Count every row. Do not average two rows that share an evaluation identity.

    The identity is bowler, delivery, phase, frame index, and front leg. If that
    identity appears more than once, every copy is counted in
    ``duplicate_identity_rows`` and left out of the error means. Conflicting
    angles are not merged, and identical repeats are not counted twice.
    Different deliveries remain separate observations.
    """
    duplicated = _duplicate_identities(rows)
    unique = [row for row in rows if _evaluation_identity(row) not in duplicated]
    ffc = [row for row in unique if row.status == "compared" and row.phase == "FFC"]
    release = [row for row in unique if row.status == "compared" and row.phase == "Release"]
    return AngleComparisonSummary(
        requested=len(rows),
        compared=sum(row.status == "compared" for row in unique),
        reference_missing=sum(row.status == "reference_missing" for row in unique),
        measurement_unavailable=sum(row.status == "unavailable" for row in unique),
        mismatches=sum(row.status == "mismatch" for row in unique),
        duplicate_identity_rows=sum(_evaluation_identity(row) in duplicated for row in rows),
        ffc=_phase_summary("FFC", ffc),
        release=_phase_summary("Release", release),
    )


def _evaluation_identity(
    row: FrontKneeAngleComparison,
) -> tuple[str, str, str, int | None, str | None]:
    return (row.bowler_id, row.delivery_id, row.phase, row.frame_index, row.front_leg)


def _duplicate_identities(
    rows: Sequence[FrontKneeAngleComparison],
) -> set[tuple[str, str, str, int | None, str | None]]:
    seen: set[tuple[str, str, str, int | None, str | None]] = set()
    duplicated: set[tuple[str, str, str, int | None, str | None]] = set()
    for row in rows:
        identity = _evaluation_identity(row)
        if identity in seen:
            duplicated.add(identity)
        seen.add(identity)
    return duplicated


def _phase_summary(phase: str, rows: Sequence[FrontKneeAngleComparison]) -> PhaseAngleErrorSummary:
    signed = [row.signed_error_degrees for row in rows if row.signed_error_degrees is not None]
    if not signed:
        return PhaseAngleErrorSummary(phase, 0, None, None, None)
    absolute = [abs(value) for value in signed]
    return PhaseAngleErrorSummary(
        phase,
        len(signed),
        sum(signed) / len(signed),
        sum(absolute) / len(absolute),
        max(absolute),
    )


def _result(
    measurement: FrontKneeAngle,
    bowler_id: str,
    delivery_id: str,
    reference: ManualAngleReference | None,
    signed: float | None,
    status: str,
    reason: str,
) -> FrontKneeAngleComparison:
    return FrontKneeAngleComparison(
        bowler_id=bowler_id,
        delivery_id=delivery_id,
        phase=measurement.phase,
        frame_index=measurement.frame_index,
        front_leg=measurement.front_leg,
        automatic_angle_degrees=measurement.angle_degrees,
        reference_angle_degrees=None if reference is None else reference.reference_angle_degrees,
        signed_error_degrees=signed,
        absolute_error_degrees=None if signed is None else abs(signed),
        status=status,
        reason=reason,
        review_status=measurement.review_status,
        warnings=measurement.warnings,
        measurement_source=measurement.source,
        reference_source=None if reference is None else reference.reference_source,
    )


def _required_id(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise AngleComparisonError(f"{field_name} must be a string, got {type(value).__name__}.")
    text = value.strip()
    if not text:
        raise AngleComparisonError(f"{field_name} must not be empty.")
    return text


def _require_angle(field_name: str, value: object) -> None:
    if not _angle_ok(value):
        raise AngleComparisonError(f"{field_name} must be a finite number in 0..180 degrees, got {value!r}.")


def _angle_ok(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    return math.isfinite(number) and 0.0 <= number <= 180.0


def _assert_measurement_source(measurement: FrontKneeAngle) -> None:
    if measurement.source != SOURCE:
        raise AngleComparisonError("Measurement source must stay the raw 2D MediaPipe landmarks.")
