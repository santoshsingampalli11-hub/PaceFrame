"""Synthetic checks that stored pixels are the angle inputs. Not a validation study."""

import math

import pytest

from app.biomechanics.front_knee import front_knee_angle
from app.biomechanics.geometry import Point2D, angle_abc_degrees
from app.pilot.measurement_pdf import render_measurement_pdf
from app.pose.landmarks import Landmark, PoseFrame


def _frame() -> PoseFrame:
    points = {
        "left_hip": (0.2, 0.3),
        "left_knee": (0.45, 0.55),
        "left_ankle": (0.7, 0.4),
    }
    landmarks = {name: Landmark(name, x, y, 0.81, 0.64) for name, (x, y) in points.items()}
    return PoseFrame(12, 12 / 30, 640, 360, landmarks)


def test_stored_pixels_match_the_values_passed_to_the_angle() -> None:
    frame = _frame()
    result = front_knee_angle(frame, "left", "FFC")
    evidence = result.calculation_evidence
    assert evidence is not None
    assert evidence.front_leg == "left"
    assert evidence.landmark_names == ("left_hip", "left_knee", "left_ankle")
    assert evidence.frame_index == 12
    assert evidence.frame_timestamp_seconds == pytest.approx(12 / 30)
    assert (evidence.image_width_px, evidence.image_height_px) == (640, 360)
    hip = Point2D(evidence.hip.x_px, evidence.hip.y_px)
    knee = Point2D(evidence.knee.x_px, evidence.knee.y_px)
    ankle = Point2D(evidence.ankle.x_px, evidence.ankle.y_px)
    assert (hip.x, hip.y) == (0.2 * 640, 0.3 * 360)
    assert evidence.hip.x_normalized == pytest.approx(0.2)
    assert evidence.hip.visibility == pytest.approx(0.81)
    assert evidence.knee.presence == pytest.approx(0.64)
    recomputed = angle_abc_degrees(hip, knee, ankle)
    assert result.angle_degrees == pytest.approx(recomputed)
    assert evidence.angle_degrees == pytest.approx(recomputed)
    assert math.isfinite(recomputed)


def test_missing_and_non_finite_landmarks_do_not_invent_coordinates() -> None:
    missing = PoseFrame(4, 0.1, 100, 80, {"left_hip": Landmark("left_hip", 0.2, 0.2, 1.0, 1.0)})
    missed = front_knee_angle(missing, "left", "FFC")
    assert missed.status == "unavailable"
    assert missed.angle_degrees is None
    assert missed.calculation_evidence is None
    assert "missing" in missed.reason
    with pytest.raises(ValueError):
        Landmark("left_knee", float("nan"), 0.2, None, None)
    degenerate = PoseFrame(
        4,
        0.1,
        100,
        80,
        {
            "left_hip": Landmark("left_hip", 0.2, 0.2, None, None),
            "left_knee": Landmark("left_knee", 0.2, 0.2, None, None),
            "left_ankle": Landmark("left_ankle", 0.5, 0.5, None, None),
        },
    )
    collapsed = front_knee_angle(degenerate, "left", "FFC")
    assert collapsed.status == "unavailable"
    assert collapsed.angle_degrees is None
    assert collapsed.calculation_evidence is None
    assert "zero length" in collapsed.reason


def test_neighboring_frame_is_not_used_when_the_label_is_absent() -> None:
    from app.annotations.models import PhaseLabel
    from app.biomechanics.front_knee import front_knee_angles_at_manual_phases

    frame = _frame()
    other = PoseFrame(frame.frame_index + 1, 1.0, 640, 360, frame.landmarks)
    label = PhaseLabel("B01", "D01", ffc_frame=5, release_frame=frame.frame_index)
    ffc, release = front_knee_angles_at_manual_phases((other, frame), label, "left")
    assert ffc.status == "unavailable"
    assert ffc.calculation_evidence is None
    assert "neighboring" in ffc.reason
    assert release.frame_index == frame.frame_index
    assert release.calculation_evidence is not None


def test_old_report_without_evidence_stays_readable_and_prints() -> None:
    legacy = {
        "bowler_id": "B01",
        "delivery_id": "D01",
        "front_leg": "left",
        "video_sha256": "abc123",
        "ffc": {"frame_index": 3, "angle_degrees": 120.0, "status": "available", "reason": ""},
        "release": {"frame_index": 4, "angle_degrees": None, "status": "unavailable", "reason": "No pose was detected."},
    }
    current = {
        **legacy,
        "ffc": {
            **legacy["ffc"],
            "calculation_evidence": {
                "schema_version": "front-knee-evidence-v1",
                "calculation": "angle_abc_degrees",
                "definition": "unsigned interior hip-knee-ankle angle, vertex at the knee, degrees 0 to 180",
                "image_width_px": 100,
                "image_height_px": 80,
                "video_sha256": "a" * 64,
                "hip": {"name": "left_hip", "x_px": 20.0, "y_px": 10.0, "visibility": 0.5, "presence": None},
                "knee": {"name": "left_knee", "x_px": 20.0, "y_px": 40.0, "visibility": None, "presence": 0.4},
                "ankle": {"name": "left_ankle", "x_px": 40.0, "y_px": 40.0, "visibility": 0.2, "presence": 0.2},
            },
        },
    }
    old_pdf = render_measurement_pdf(legacy)
    new_pdf = render_measurement_pdf(current)
    assert old_pdf.startswith(b"%PDF-1.4")
    assert b"coordinate evidence: not stored" in old_pdf
    assert new_pdf.startswith(b"%PDF-1.4")
    assert b"left_hip" in new_pdf
    assert b"20.0" in new_pdf
    assert "calculation_evidence" not in legacy["ffc"]
