"""Tests for 2D geometry. No video, pose estimator, or FastAPI required."""

import math
import subprocess
import sys
from pathlib import Path

import pytest

from app.biomechanics import GeometryError, Point2D, angle_abc_degrees, distance

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_biomechanics_imports_without_video_pose_or_api() -> None:
    check = (
        "import sys, app.biomechanics; "
        "assert 'fastapi' not in sys.modules; "
        "assert 'cv2' not in sys.modules; "
        "assert 'mediapipe' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", check], cwd=BACKEND_DIR, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr


# --- distance --------------------------------------------------------------


def test_distance_axis_aligned() -> None:
    assert distance(Point2D(0.0, 0.0), Point2D(3.0, 0.0)) == pytest.approx(3.0)
    assert distance(Point2D(0.0, 0.0), Point2D(0.0, 4.0)) == pytest.approx(4.0)


def test_distance_3_4_5_triangle() -> None:
    assert distance(Point2D(0.0, 0.0), Point2D(3.0, 4.0)) == pytest.approx(5.0)


def test_distance_is_symmetric_and_zero_to_self() -> None:
    a = Point2D(-2.0, 7.0)
    b = Point2D(1.5, -0.5)
    assert distance(a, a) == pytest.approx(0.0)
    assert distance(a, b) == pytest.approx(distance(b, a))


def test_distance_negative_coordinates() -> None:
    assert distance(Point2D(-1.0, -1.0), Point2D(-4.0, -5.0)) == pytest.approx(5.0)


def test_distance_translation_invariance() -> None:
    original = distance(Point2D(1.0, 2.0), Point2D(4.0, 6.0))
    shifted = distance(Point2D(11.0, -3.0), Point2D(14.0, 1.0))
    assert shifted == pytest.approx(original)


def test_distance_very_small_and_large_finite_points() -> None:
    assert distance(Point2D(0.0, 0.0), Point2D(1e-12, 0.0)) == pytest.approx(1e-12)
    assert distance(Point2D(0.0, 0.0), Point2D(1e6, 0.0)) == pytest.approx(1e6)


# --- known angles ----------------------------------------------------------


def test_angle_90_degrees() -> None:
    assert angle_abc_degrees(Point2D(0.0, 1.0), Point2D(0.0, 0.0), Point2D(1.0, 0.0)) == pytest.approx(
        90.0
    )


def test_angle_180_degrees() -> None:
    assert angle_abc_degrees(Point2D(0.0, 0.0), Point2D(1.0, 0.0), Point2D(2.0, 0.0)) == pytest.approx(
        180.0
    )


def test_angle_0_degrees() -> None:
    assert angle_abc_degrees(Point2D(2.0, 0.0), Point2D(0.0, 0.0), Point2D(1.0, 0.0)) == pytest.approx(
        0.0
    )


def test_angle_45_degrees() -> None:
    assert angle_abc_degrees(Point2D(1.0, 0.0), Point2D(0.0, 0.0), Point2D(1.0, 1.0)) == pytest.approx(
        45.0
    )


def test_angle_acute() -> None:
    # arccos(0.6) between (3,0) and (3,4) from the origin is arctan(4/3) ≈ 53.13°.
    angle = angle_abc_degrees(Point2D(3.0, 0.0), Point2D(0.0, 0.0), Point2D(3.0, 4.0))
    assert angle == pytest.approx(math.degrees(math.atan2(4.0, 3.0)))
    assert 0.0 < angle < 90.0


def test_angle_obtuse() -> None:
    angle = angle_abc_degrees(Point2D(-1.0, 0.0), Point2D(0.0, 0.0), Point2D(1.0, 1.0))
    assert angle == pytest.approx(135.0)
    assert 90.0 < angle < 180.0


def test_angle_is_unsigned() -> None:
    clockwise = angle_abc_degrees(Point2D(1.0, 0.0), Point2D(0.0, 0.0), Point2D(0.0, -1.0))
    counter = angle_abc_degrees(Point2D(1.0, 0.0), Point2D(0.0, 0.0), Point2D(0.0, 1.0))
    assert clockwise == pytest.approx(90.0)
    assert counter == pytest.approx(90.0)


def test_angle_is_invariant_under_translation() -> None:
    shift_x, shift_y = 12.5, -8.0

    def shifted(x: float, y: float) -> Point2D:
        return Point2D(x + shift_x, y + shift_y)

    original = angle_abc_degrees(Point2D(0.0, 1.0), Point2D(0.0, 0.0), Point2D(1.0, 0.0))
    moved = angle_abc_degrees(shifted(0.0, 1.0), shifted(0.0, 0.0), shifted(1.0, 0.0))
    assert moved == pytest.approx(original)


def test_angle_negative_coordinates() -> None:
    assert angle_abc_degrees(Point2D(-1.0, 0.0), Point2D(0.0, 0.0), Point2D(0.0, -1.0)) == pytest.approx(
        90.0
    )


def test_angle_very_small_valid_vectors() -> None:
    scale = 1e-9
    angle = angle_abc_degrees(
        Point2D(scale, 0.0), Point2D(0.0, 0.0), Point2D(0.0, scale)
    )
    assert angle == pytest.approx(90.0)


def test_angle_clips_cosine_at_collinear_points() -> None:
    # Long nearly-collinear segments can push the cosine slightly outside [-1, 1].
    angle = angle_abc_degrees(
        Point2D(0.0, 0.0), Point2D(1e8, 0.0), Point2D(2e8, 1e-8)
    )
    assert 0.0 <= angle <= 180.0
    assert math.isfinite(angle)


def test_angle_abc_equals_angle_cba() -> None:
    a, b, c = Point2D(3.0, 0.0), Point2D(0.0, 0.0), Point2D(1.0, 2.0)
    assert angle_abc_degrees(a, b, c) == pytest.approx(angle_abc_degrees(c, b, a))


def test_angle_is_invariant_under_positive_scaling() -> None:
    original = angle_abc_degrees(Point2D(1.0, 0.0), Point2D(0.0, 0.0), Point2D(1.0, 1.0))
    scaled = angle_abc_degrees(Point2D(4.0, 0.0), Point2D(0.0, 0.0), Point2D(4.0, 4.0))
    assert scaled == pytest.approx(original)


def test_angle_stays_in_closed_unit_interval() -> None:
    samples = [
        (Point2D(1.0, 0.0), Point2D(0.0, 0.0), Point2D(2.0, 0.0)),
        (Point2D(-1.0, 0.0), Point2D(0.0, 0.0), Point2D(1.0, 0.0)),
        (Point2D(0.0, 300.0), Point2D(0.0, 0.0), Point2D(1.0, 300.0)),
        (Point2D(0.0, 0.0), Point2D(0.0, 300.0), Point2D(1.0, 600.0)),
    ]
    for a, b, c in samples:
        angle = angle_abc_degrees(a, b, c)
        assert 0.0 <= angle <= 180.0
        assert math.isfinite(angle)


def test_angle_nearly_parallel_is_near_zero() -> None:
    angle = angle_abc_degrees(Point2D(1.0, 0.0), Point2D(0.0, 0.0), Point2D(1.0, 1e-8))
    assert 0.0 <= angle < 1e-5
    assert math.isfinite(angle)


def test_angle_nearly_anti_parallel_is_near_180() -> None:
    angle = angle_abc_degrees(Point2D(-1.0, 0.0), Point2D(0.0, 0.0), Point2D(1.0, 1e-8))
    assert 179.999 < angle <= 180.0
    assert math.isfinite(angle)


def test_pixel_scale_near_straight_angle_matches_atan2() -> None:
    # 1 px offset over 300 px: typical image geometry, not a 3D joint claim.
    angle = angle_abc_degrees(Point2D(0.0, 0.0), Point2D(0.0, 300.0), Point2D(1.0, 600.0))
    expected = math.degrees(math.atan2(1.0, 300.0))
    assert angle == pytest.approx(180.0 - expected)


# --- invalid inputs --------------------------------------------------------


def test_zero_length_ba_is_rejected() -> None:
    with pytest.raises(GeometryError, match="zero length"):
        angle_abc_degrees(Point2D(1.0, 1.0), Point2D(1.0, 1.0), Point2D(2.0, 1.0))


def test_zero_length_bc_is_rejected() -> None:
    with pytest.raises(GeometryError, match="zero length"):
        angle_abc_degrees(Point2D(0.0, 0.0), Point2D(1.0, 1.0), Point2D(1.0, 1.0))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_point_is_rejected(value: float) -> None:
    with pytest.raises(GeometryError, match="finite"):
        Point2D(value, 0.0)
    with pytest.raises(GeometryError, match="finite"):
        Point2D(0.0, value)
