"""Synthetic checks for manual front-knee reference errors. Not bowling validation."""

import pytest

from app.biomechanics.angle_comparison import (
    AngleComparisonError,
    ManualAngleReference,
    compare_front_knee_angle,
    summarise_angle_comparisons,
)
from app.biomechanics.front_knee import SOURCE, FrontKneeAngle


def _measurement(
    angle: float | None,
    *,
    phase: str = "FFC",
    frame: int = 10,
    leg: str = "left",
    warnings: tuple[str, ...] = (),
    reason: str = "",
) -> FrontKneeAngle:
    if angle is None:
        return FrontKneeAngle(
            "2d_front_knee_angle",
            phase,
            frame,
            leg,
            None,
            "unavailable",
            reason or "No pose was detected.",
            SOURCE,
            warnings,
            (),
            "unavailable",
        )
    review = "review_required" if warnings else "no_structural_warning"
    return FrontKneeAngle(
        "2d_front_knee_angle",
        phase,
        frame,
        leg,
        angle,
        "available",
        "",
        SOURCE,
        warnings,
        (),
        review,
    )


def _reference(
    angle: float = 90.0,
    *,
    bowler: str = "B01",
    delivery: str = "D01",
    phase: str = "FFC",
    frame: int = 10,
    leg: str = "left",
) -> ManualAngleReference:
    return ManualAngleReference(bowler, delivery, phase, frame, leg, angle, "manual")


def _compare(measurement: FrontKneeAngle, reference: ManualAngleReference | None, bowler: str = "B01", delivery: str = "D01"):
    return compare_front_knee_angle(measurement, reference, bowler, delivery)


def test_exact_agreement_has_zero_signed_error() -> None:
    result = _compare(_measurement(90.0), _reference(90.0))
    assert result.status == "compared"
    assert result.signed_error_degrees == pytest.approx(0.0)
    assert result.absolute_error_degrees == pytest.approx(0.0)
    assert "not laboratory ground truth" in result.reason
    assert result.measurement_source == SOURCE


def test_automatic_angle_above_and_below_the_reference() -> None:
    above = _compare(_measurement(100.0), _reference(90.0))
    below = _compare(_measurement(80.0), _reference(90.0))
    assert above.signed_error_degrees == pytest.approx(10.0)
    assert above.absolute_error_degrees == pytest.approx(10.0)
    assert below.signed_error_degrees == pytest.approx(-10.0)
    assert below.absolute_error_degrees == pytest.approx(10.0)


def test_angle_bounds_zero_and_180_can_be_compared() -> None:
    low = _compare(_measurement(0.0), _reference(0.0))
    high = _compare(_measurement(180.0), _reference(180.0))
    assert low.status == "compared" and low.signed_error_degrees == pytest.approx(0.0)
    assert high.status == "compared" and high.signed_error_degrees == pytest.approx(0.0)


def test_identity_phase_frame_and_side_must_all_match() -> None:
    measurement = _measurement(90.0)
    cases = [
        (_reference(bowler="B02"), "B01", "D01", "Bowler"),
        (_reference(delivery="D02"), "B01", "D01", "Delivery"),
        (_reference(phase="Release"), "B01", "D01", "Phase"),
        (_reference(frame=11), "B01", "D01", "Frame"),
        (_reference(leg="right"), "B01", "D01", "Front leg"),
    ]
    for reference, bowler, delivery, expected in cases:
        result = _compare(measurement, reference, bowler, delivery)
        assert result.status == "mismatch"
        assert result.signed_error_degrees is None
        assert result.absolute_error_degrees is None
        assert expected in result.reason


def test_missing_reference_and_unavailable_measurement_are_not_zero() -> None:
    missing = _compare(_measurement(90.0), None)
    unavailable = _compare(_measurement(None), _reference())
    assert missing.status == "reference_missing"
    assert missing.signed_error_degrees is None
    assert missing.automatic_angle_degrees == pytest.approx(90.0)
    assert unavailable.status == "unavailable"
    assert unavailable.signed_error_degrees is None
    assert unavailable.automatic_angle_degrees is None
    assert "not a zero error" in unavailable.reason


def test_review_required_measurement_keeps_warning_and_can_be_compared() -> None:
    warning = ("left_ankle is outside normalized image bounds.",)
    measurement = _measurement(95.0, warnings=warning)
    result = _compare(measurement, _reference(90.0))
    assert result.status == "compared"
    assert result.signed_error_degrees == pytest.approx(5.0)
    assert result.review_status == "review_required"
    assert result.warnings == warning
    assert "not an accuracy grade" in result.reason


def test_invalid_reference_angles_are_rejected() -> None:
    for value in (float("nan"), float("inf"), True, -1.0, 181.0):
        with pytest.raises(AngleComparisonError, match="0..180"):
            _reference(value)


def test_duplicate_evaluation_identity_is_excluded_from_error_statistics() -> None:
    first = _compare(_measurement(100.0), _reference(90.0))
    conflicting = _compare(_measurement(80.0), _reference(90.0))
    summary = summarise_angle_comparisons((first, conflicting))
    assert summary.requested == 2
    assert summary.duplicate_identity_rows == 2
    assert summary.compared == 0
    assert summary.ffc.pair_count == 0
    assert summary.ffc.mean_signed_error_degrees is None
    assert summary.ffc.mean_absolute_error_degrees is None
    assert summary.ffc.max_absolute_error_degrees is None


def test_distinct_deliveries_keep_separate_ffc_and_release_errors() -> None:
    ffc_high = _compare(_measurement(100.0), _reference(90.0))
    ffc_other = _compare(_measurement(80.0), _reference(90.0, delivery="D02"), delivery="D02")
    release = _compare(_measurement(70.0, phase="Release"), _reference(74.0, phase="Release"))
    summary = summarise_angle_comparisons((ffc_high, ffc_other, release))
    assert summary.requested == 3
    assert summary.duplicate_identity_rows == 0
    assert summary.compared == 3
    assert summary.ffc.pair_count == 2
    assert summary.ffc.mean_signed_error_degrees == pytest.approx(0.0)
    assert summary.ffc.mean_absolute_error_degrees == pytest.approx(10.0)
    assert summary.ffc.max_absolute_error_degrees == pytest.approx(10.0)
    assert summary.release.pair_count == 1
    assert summary.release.mean_signed_error_degrees == pytest.approx(-4.0)
    assert summary.release.mean_absolute_error_degrees == pytest.approx(4.0)


def test_empty_and_all_unavailable_summaries_do_not_invent_zero_error() -> None:
    empty = summarise_angle_comparisons(())
    assert empty.requested == 0
    assert empty.compared == 0
    assert empty.duplicate_identity_rows == 0
    assert empty.ffc.pair_count == 0
    assert empty.ffc.mean_signed_error_degrees is None
    assert empty.ffc.mean_absolute_error_degrees is None
    assert empty.release.max_absolute_error_degrees is None

    rows = (
        _compare(_measurement(None, frame=1), _reference(frame=1)),
        _compare(_measurement(90.0, frame=2), None),
        _compare(_measurement(90.0, frame=4), _reference(frame=3)),
    )
    summary = summarise_angle_comparisons(rows)
    assert summary.requested == 3
    assert summary.compared == 0
    assert summary.measurement_unavailable == 1
    assert summary.reference_missing == 1
    assert summary.mismatches == 1
    assert summary.ffc.mean_absolute_error_degrees is None
    assert summary.release.mean_signed_error_degrees is None


def test_comparison_does_not_mutate_the_measurement() -> None:
    warning = ("left_knee has no visibility score.",)
    measurement = _measurement(90.0, warnings=warning)
    before = (measurement.angle_degrees, measurement.warnings, measurement.review_status)
    _compare(measurement, _reference(88.0))
    assert (measurement.angle_degrees, measurement.warnings, measurement.review_status) == before


def test_manual_phase_frames_flow_into_separate_reference_errors() -> None:
    from app.annotations.models import PhaseLabel
    from app.biomechanics.front_knee import front_knee_angles_at_manual_phases
    from app.pose.landmarks import Landmark, PoseFrame

    def frame(index: int) -> PoseFrame:
        landmarks = {
            "left_hip": Landmark("left_hip", 0.5, 0.2, 1.0, 1.0),
            "left_knee": Landmark("left_knee", 0.5, 0.5, 1.0, 1.0),
            "left_ankle": Landmark("left_ankle", 0.5, 0.8, 1.0, 1.0),
        }
        return PoseFrame(index, index / 25.0, 100, 100, landmarks)

    label = PhaseLabel("B01", "D01", ffc_frame=3, release_frame=7)
    ffc, release = front_knee_angles_at_manual_phases([frame(3), frame(7)], label, "left")
    ffc_error = compare_front_knee_angle(
        ffc, ManualAngleReference("B01", "D01", "FFC", 3, "left", 170.0), "B01", "D01"
    )
    release_error = compare_front_knee_angle(
        release, ManualAngleReference("B01", "D01", "Release", 7, "left", 180.0), "B01", "D01"
    )
    summary = summarise_angle_comparisons((ffc_error, release_error))
    assert ffc.frame_index == 3 and release.frame_index == 7
    assert ffc.angle_degrees == pytest.approx(180.0)
    assert ffc_error.signed_error_degrees == pytest.approx(10.0)
    assert release_error.signed_error_degrees == pytest.approx(0.0)
    assert ffc_error.measurement_source == SOURCE
    assert summary.duplicate_identity_rows == 0
    assert summary.ffc.pair_count == 1
    assert summary.release.pair_count == 1
    assert summary.ffc.mean_absolute_error_degrees == pytest.approx(10.0)
