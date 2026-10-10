"""Synthetic checks for the 2D front-knee angle. Not pose-accuracy validation."""

import math

import pytest

from app.annotations.models import PhaseLabel
from app.biomechanics.front_knee import (
    front_knee_angle,
    front_knee_angles_at_manual_phases,
)
from app.biomechanics.geometry import Point2D, angle_abc_degrees
from app.pose.landmarks import Landmark, PoseFrame


def _landmark(name: str, x: float, y: float, visibility: float = 1.0) -> Landmark:
    return Landmark(name, x, y, visibility, 1.0)


def _frame(
    index: int,
    points: dict[str, tuple[float, float]],
    *,
    width: int = 100,
    height: int = 100,
    visibility: float = 1.0,
) -> PoseFrame:
    landmarks = {
        name: _landmark(name, x, y, visibility) for name, (x, y) in points.items()
    }
    return PoseFrame(index, index / 25.0, width, height, landmarks)


def _leg(prefix: str, hip: tuple[float, float], knee: tuple[float, float], ankle: tuple[float, float]) -> dict[str, tuple[float, float]]:
    return {
        f"{prefix}_hip": hip,
        f"{prefix}_knee": knee,
        f"{prefix}_ankle": ankle,
    }


def _straight() -> dict[str, tuple[float, float]]:
    return _leg("left", (0.5, 0.2), (0.5, 0.5), (0.5, 0.8))


def _right_angle() -> dict[str, tuple[float, float]]:
    return _leg("left", (0.5, 0.2), (0.5, 0.5), (0.8, 0.5))


def _bent_120() -> dict[str, tuple[float, float]]:
    return _leg("left", (0.8, 0.5), (0.5, 0.5), (0.35, 0.5 + 0.15 * math.sqrt(3)))


def test_straight_knee_is_180_degrees() -> None:
    result = front_knee_angle(_frame(4, _straight()), "left", "FFC")
    assert result.status == "available"
    assert result.angle_degrees == pytest.approx(180.0)
    assert result.warnings == ()


def test_right_angle_knee_is_90_degrees() -> None:
    result = front_knee_angle(_frame(4, _right_angle()), "left", "Release")
    assert result.angle_degrees == pytest.approx(90.0)


def test_bent_knee_is_120_degrees_via_the_shared_angle_function() -> None:
    points = _bent_120()
    frame = _frame(4, points)
    result = front_knee_angle(frame, "left", "FFC")
    expected = angle_abc_degrees(
        Point2D(0.8 * 100, 0.5 * 100),
        Point2D(0.5 * 100, 0.5 * 100),
        Point2D(0.35 * 100, (0.5 + 0.15 * math.sqrt(3)) * 100),
    )
    assert expected == pytest.approx(120.0)
    assert result.angle_degrees == pytest.approx(expected)
    assert result.metric == "2d_front_knee_angle"
    assert result.source == "raw_2d_mediapipe_landmarks"


def test_non_square_frame_uses_pixels_not_normalized_coordinates() -> None:
    hip, knee, ankle = (0.5, 0.2), (0.5, 0.5), (0.8, 0.2)
    frame = _frame(1, _leg("left", hip, knee, ankle), width=200, height=100)
    result = front_knee_angle(frame, "left", "FFC")
    pixel_angle = angle_abc_degrees(
        Point2D(hip[0] * 200, hip[1] * 100),
        Point2D(knee[0] * 200, knee[1] * 100),
        Point2D(ankle[0] * 200, ankle[1] * 100),
    )
    normalized_angle = angle_abc_degrees(Point2D(*hip), Point2D(*knee), Point2D(*ankle))
    assert pixel_angle != pytest.approx(normalized_angle)
    assert result.angle_degrees == pytest.approx(pixel_angle)


def test_explicit_side_selects_that_legs_landmarks() -> None:
    points = {}
    points.update(_leg("left", (0.5, 0.2), (0.5, 0.5), (0.5, 0.8)))
    points.update(_leg("right", (0.5, 0.2), (0.5, 0.5), (0.8, 0.5)))
    frame = _frame(3, points)
    assert front_knee_angle(frame, "left", "FFC").angle_degrees == pytest.approx(180.0)
    assert front_knee_angle(frame, "right", "FFC").angle_degrees == pytest.approx(90.0)


def test_unknown_side_is_not_inferred() -> None:
    frame = _frame(3, _straight())
    for side in ("", "front", "LEFT", "screen_left"):
        result = front_knee_angle(frame, side, "FFC")
        assert result.status == "unavailable"
        assert result.angle_degrees is None
        assert result.front_leg is None
        assert "No side was inferred" in result.reason


def test_zero_visibility_does_not_block_the_angle() -> None:
    result = front_knee_angle(_frame(2, _straight(), visibility=0.0), "left", "FFC")
    assert result.status == "available"
    assert result.angle_degrees == pytest.approx(180.0)


def test_exact_frames_are_used_and_neighbors_are_not() -> None:
    frames = [
        _frame(0, _straight()),
        _frame(2, _right_angle()),
    ]
    label = PhaseLabel("B01", "D01", ffc_frame=0, release_frame=2)
    ffc, release = front_knee_angles_at_manual_phases(frames, label, "left")
    assert ffc.frame_index == 0 and ffc.angle_degrees == pytest.approx(180.0)
    assert release.frame_index == 2 and release.angle_degrees == pytest.approx(90.0)
    assert label.ffc_frame == 0 and label.release_frame == 2

    missing = PhaseLabel("B01", "D01", ffc_frame=1, release_frame=2)
    missed, kept = front_knee_angles_at_manual_phases(frames, missing, "left")
    assert missed.status == "unavailable"
    assert missed.angle_degrees is None
    assert "neighboring frame was not used" in missed.reason
    assert kept.angle_degrees == pytest.approx(90.0)


def test_missing_event_label_stays_unavailable() -> None:
    frames = [_frame(2, _straight())]
    label = PhaseLabel("B01", "D01", release_frame=2)
    ffc, release = front_knee_angles_at_manual_phases(frames, label, "left")
    assert ffc.status == "unavailable"
    assert ffc.frame_index is None
    assert "FFC was not annotated" in ffc.reason
    assert release.angle_degrees == pytest.approx(180.0)


def test_missing_pose_hip_knee_and_ankle() -> None:
    empty = PoseFrame(1, 0.0, 100, 100, {})
    assert "No pose" in front_knee_angle(empty, "left", "FFC").reason

    no_hip = _frame(1, {"left_knee": (0.5, 0.5), "left_ankle": (0.5, 0.8)})
    assert "left_hip is missing" in front_knee_angle(no_hip, "left", "FFC").reason

    no_knee = _frame(1, {"left_hip": (0.5, 0.2), "left_ankle": (0.5, 0.8)})
    assert "left_knee is missing" in front_knee_angle(no_knee, "left", "Release").reason

    no_ankle = _frame(1, {"left_hip": (0.5, 0.2), "left_knee": (0.5, 0.5)})
    assert "left_ankle is missing" in front_knee_angle(no_ankle, "left", "FFC").reason


def test_coordinate_outside_the_image_is_not_clamped() -> None:
    outside = _leg("left", (0.5, 0.2), (0.5, 0.5), (1.4, 0.2))
    result = front_knee_angle(_frame(6, outside), "left", "FFC")
    clamped = dict(outside)
    clamped["left_ankle"] = (1.0, 0.2)
    clamped_angle = front_knee_angle(_frame(6, clamped), "left", "FFC").angle_degrees
    assert result.status == "available"
    assert result.angle_degrees != pytest.approx(clamped_angle)
    assert result.angle_degrees == pytest.approx(
        angle_abc_degrees(Point2D(50, 20), Point2D(50, 50), Point2D(140, 20))
    )
    assert "not clamped" in result.warnings[0]


def test_non_finite_coordinate_is_unavailable() -> None:
    frame = _frame(1, _straight())
    object.__setattr__(frame.landmarks["left_knee"], "x", float("nan"))
    result = front_knee_angle(frame, "left", "FFC")
    assert result.status == "unavailable"
    assert "non-finite" in result.reason


def test_degenerate_points_are_unavailable() -> None:
    folded = _leg("left", (0.5, 0.5), (0.5, 0.5), (0.5, 0.8))
    result = front_knee_angle(_frame(1, folded), "left", "Release")
    assert result.status == "unavailable"
    assert result.angle_degrees is None
    assert "zero length" in result.reason


def test_duplicate_and_invalid_frame_indices_block_calculation() -> None:
    label = PhaseLabel("B01", "D01", ffc_frame=1, release_frame=2)
    duplicated = [_frame(1, _straight()), _frame(1, _right_angle())]
    ffc, release = front_knee_angles_at_manual_phases(duplicated, label, "left")
    assert ffc.status == "unavailable" and release.status == "unavailable"
    assert "repeats frame index 1" in ffc.reason

    negative = PoseFrame(-1, 0.0, 100, 100, {})
    ffc, release = front_knee_angles_at_manual_phases([negative, _frame(2, _straight())], label, "left")
    assert "invalid frame index" in ffc.reason
    assert release.angle_degrees is None

    empty_ffc, empty_release = front_knee_angles_at_manual_phases([], label, "left")
    assert "No pose frames" in empty_ffc.reason
    assert empty_release.angle_degrees is None


def test_one_pass_frame_iterable_is_not_reported_as_missing() -> None:
    frames = (_frame(0, _straight()), _frame(2, _right_angle()))
    label = PhaseLabel("B01", "D01", ffc_frame=0, release_frame=2)
    ffc, release = front_knee_angles_at_manual_phases((frame for frame in frames), label, "left")
    assert ffc.status == "available"
    assert ffc.frame_index == 0
    assert ffc.angle_degrees == pytest.approx(180.0)
    assert release.status == "available"
    assert release.frame_index == 2
    assert release.angle_degrees == pytest.approx(90.0)


def test_outside_image_warning_survives_a_degenerate_angle() -> None:
    folded = _leg("left", (1.4, 0.5), (1.4, 0.5), (0.5, 0.8))
    result = front_knee_angle(_frame(1, folded), "left", "FFC")
    assert result.status == "unavailable"
    assert result.angle_degrees is None
    assert "zero length" in result.reason
    assert result.warnings
    assert "not clamped" in result.warnings[0]


def test_original_pose_frame_is_not_mutated() -> None:
    frame = _frame(4, _straight())
    before = {name: (item.x, item.y) for name, item in frame.landmarks.items()}
    landmark_ids = {name: id(item) for name, item in frame.landmarks.items()}
    front_knee_angle(frame, "left", "FFC")
    assert {name: (item.x, item.y) for name, item in frame.landmarks.items()} == before
    assert {name: id(item) for name, item in frame.landmarks.items()} == landmark_ids


def test_available_result_carries_raw_landmark_evidence() -> None:
    result = front_knee_angle(_frame(4, _straight()), "left", "FFC")
    assert result.status == "available"
    assert result.review_status == "no_structural_warning"
    assert result.angle_degrees == pytest.approx(180.0)
    assert result.source == "raw_2d_mediapipe_landmarks"
    assert [item.role for item in result.evidence] == ["hip", "knee", "ankle"]
    assert [item.name for item in result.evidence] == ["left_hip", "left_knee", "left_ankle"]
    assert all(item.available and item.coordinates_finite and item.outside_image is False for item in result.evidence)
    assert result.evidence[0].visibility == 1.0
    assert result.evidence[0].presence == 1.0


def test_missing_visibility_requires_review_and_keeps_the_angle() -> None:
    landmarks = {
        name: Landmark(name, x, y, None, 1.0) for name, (x, y) in _straight().items()
    }
    result = front_knee_angle(PoseFrame(2, 0.0, 100, 100, landmarks), "left", "FFC")
    assert result.status == "available"
    assert result.angle_degrees == pytest.approx(180.0)
    assert result.review_status == "review_required"
    assert "no visibility" in result.warnings[0]
    assert "not landmark accuracy" in result.warnings[0]
    scored = front_knee_angle(_frame(2, _straight(), visibility=0.0), "left", "FFC")
    assert scored.angle_degrees == pytest.approx(180.0)
    assert scored.review_status == "no_structural_warning"


def test_out_of_frame_point_requires_review_without_clamping() -> None:
    outside = _leg("left", (0.5, 0.2), (0.5, 0.5), (1.4, 0.2))
    result = front_knee_angle(_frame(6, outside), "left", "FFC")
    assert result.status == "available"
    assert result.review_status == "review_required"
    assert result.evidence[2].outside_image is True
    assert result.angle_degrees == pytest.approx(
        angle_abc_degrees(Point2D(50, 20), Point2D(50, 50), Point2D(140, 20))
    )


def test_unavailable_result_is_not_zero_and_keeps_its_warning() -> None:
    folded = _leg("left", (1.4, 0.5), (1.4, 0.5), (0.5, 0.8))
    result = front_knee_angle(_frame(1, folded), "left", "FFC")
    assert result.status == "unavailable"
    assert result.review_status == "unavailable"
    assert result.angle_degrees is None
    assert result.warnings
    assert result.evidence[0].outside_image is True
    assert result.evidence[0].name == "left_hip"


def test_missing_frame_and_invalid_leg_do_not_invent_an_angle() -> None:
    frames = [_frame(5, _straight())]
    label = PhaseLabel("B01", "D01", ffc_frame=1, release_frame=5)
    missed, kept = front_knee_angles_at_manual_phases(frames, label, "left")
    assert missed.angle_degrees is None
    assert missed.review_status == "unavailable"
    assert missed.evidence == ()
    assert "neighboring frame was not used" in missed.reason
    assert kept.angle_degrees == pytest.approx(180.0)
    assert kept.source == "raw_2d_mediapipe_landmarks"
    invalid = front_knee_angle(frames[0], "front", "Release")
    assert invalid.angle_degrees is None
    assert invalid.review_status == "unavailable"
    assert invalid.front_leg is None
    assert invalid.evidence == ()
