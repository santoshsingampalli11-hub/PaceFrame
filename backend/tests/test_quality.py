"""Tests for Phase 3.5 pose-sequence diagnostics. No accept/reject thresholds."""

import math
import subprocess
import sys
from pathlib import Path

import pytest

from app.pose.landmarks import LANDMARK_NAMES, Landmark, PoseFrame
from app.quality import (
    QualityDiagnostics,
    QualityDiagnosticsError,
    diagnose_pose_frames,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
WIDTH = 200
HEIGHT = 100


def _landmark(name: str, x: float, y: float, visibility: float | None = 1.0, presence: float | None = 1.0) -> Landmark:
    return Landmark(name=name, x=x, y=y, visibility=visibility, presence=presence)


def _empty_frame(index: int) -> PoseFrame:
    return PoseFrame(
        frame_index=index,
        timestamp_seconds=index / 30.0,
        image_width=WIDTH,
        image_height=HEIGHT,
        landmarks={},
    )


def _pose_frame(
    index: int,
    landmarks: dict[str, Landmark] | None = None,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> PoseFrame:
    if landmarks is None:
        landmarks = {
            name: _landmark(name, 0.5, 0.5)
            for name in ("left_hip", "right_hip", "left_knee")
        }
    return PoseFrame(
        frame_index=index,
        timestamp_seconds=index / 30.0,
        image_width=width,
        image_height=height,
        landmarks=landmarks,
    )


def test_quality_imports_without_mediapipe_or_api() -> None:
    check = (
        "import sys, app.quality; "
        "assert 'fastapi' not in sys.modules; "
        "assert 'cv2' not in sys.modules; "
        "assert 'mediapipe' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", check], cwd=BACKEND_DIR, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr


def test_empty_sequence_is_rejected() -> None:
    with pytest.raises(QualityDiagnosticsError, match="empty"):
        diagnose_pose_frames([])


def test_all_frames_without_pose() -> None:
    result = diagnose_pose_frames([_empty_frame(0), _empty_frame(1), _empty_frame(2)])

    assert result.frame_count == 3
    assert result.frames_with_pose == 0
    assert result.pose_coverage == pytest.approx(0.0)
    assert result.longest_run_without_pose == 3
    assert result.missing_pose_run_count == 1
    assert result.hip_centre_motion.pair_count == 0
    assert result.hip_centre_motion.mean_normalized_displacement is None
    assert all(signal.frames_with_landmark == 0 for signal in result.landmark_signals)


def test_all_frames_with_pose_have_full_coverage() -> None:
    result = diagnose_pose_frames([_pose_frame(0), _pose_frame(1)])

    assert result.frames_with_pose == 2
    assert result.pose_coverage == pytest.approx(1.0)
    assert result.longest_run_without_pose == 0
    assert result.missing_pose_run_count == 0


def test_pose_coverage_and_missing_runs() -> None:
    frames = [
        _empty_frame(0),
        _empty_frame(1),
        _pose_frame(2),
        _empty_frame(3),
        _pose_frame(4),
        _pose_frame(5),
        _empty_frame(6),
        _empty_frame(7),
        _empty_frame(8),
    ]

    result = diagnose_pose_frames(frames)

    assert result.frame_count == 9
    assert result.frames_with_pose == 3
    assert result.pose_coverage == pytest.approx(3 / 9)
    assert result.longest_run_without_pose == 3
    assert result.missing_pose_run_count == 3


def test_landmark_visibility_and_presence_means() -> None:
    frames = [
        _pose_frame(
            0,
            {
                "left_knee": _landmark("left_knee", 0.4, 0.7, visibility=0.2, presence=0.9),
                "left_hip": _landmark("left_hip", 0.4, 0.5, visibility=None, presence=None),
            },
        ),
        _pose_frame(
            1,
            {
                "left_knee": _landmark("left_knee", 0.41, 0.71, visibility=0.8, presence=0.5),
                "left_hip": _landmark("left_hip", 0.4, 0.5, visibility=0.4, presence=1.0),
            },
        ),
        _empty_frame(2),
    ]

    result = diagnose_pose_frames(frames)
    by_name = {signal.name: signal for signal in result.landmark_signals}

    assert list(by_name) == list(LANDMARK_NAMES)
    knee = by_name["left_knee"]
    assert knee.frames_with_landmark == 2
    assert knee.visibility_count == 2
    assert knee.mean_visibility == pytest.approx(0.5)
    assert knee.presence_count == 2
    assert knee.mean_presence == pytest.approx(0.7)

    hip = by_name["left_hip"]
    assert hip.frames_with_landmark == 2
    assert hip.visibility_count == 1
    assert hip.mean_visibility == pytest.approx(0.4)
    assert hip.presence_count == 1
    assert hip.mean_presence == pytest.approx(1.0)

    missing = by_name["right_ankle"]
    assert missing.frames_with_landmark == 0
    assert missing.mean_visibility is None
    assert missing.mean_presence is None


def _hips(index: int, left: tuple[float, float], right: tuple[float, float], *, width: int = WIDTH, height: int = HEIGHT) -> PoseFrame:
    return _pose_frame(
        index,
        {
            "left_hip": _landmark("left_hip", left[0], left[1]),
            "right_hip": _landmark("right_hip", right[0], right[1]),
        },
        width=width,
        height=height,
    )


def _assert_finite_motion(motion) -> None:
    assert motion.mean_normalized_displacement is not None
    assert motion.median_normalized_displacement is not None
    assert motion.max_normalized_displacement is not None
    assert math.isfinite(motion.mean_normalized_displacement)
    assert math.isfinite(motion.median_normalized_displacement)
    assert math.isfinite(motion.max_normalized_displacement)


def test_identical_normalized_hip_centres_give_zero_movement() -> None:
    frames = [
        _hips(0, (0.40, 0.50), (0.60, 0.50)),
        _hips(1, (0.40, 0.50), (0.60, 0.50)),
    ]
    motion = diagnose_pose_frames(frames).hip_centre_motion

    assert motion.pair_count == 1
    _assert_finite_motion(motion)
    assert motion.mean_normalized_displacement == pytest.approx(0.0)
    assert motion.median_normalized_displacement == pytest.approx(0.0)
    assert motion.max_normalized_displacement == pytest.approx(0.0)


def test_horizontal_normalized_hip_movement() -> None:
    # Centre x: 0.50 → 0.60, y unchanged → movement 0.10
    frames = [
        _hips(0, (0.40, 0.50), (0.60, 0.50)),
        _hips(1, (0.50, 0.50), (0.70, 0.50)),
    ]
    motion = diagnose_pose_frames(frames).hip_centre_motion

    assert motion.pair_count == 1
    _assert_finite_motion(motion)
    assert motion.mean_normalized_displacement == pytest.approx(0.10)


def test_vertical_normalized_hip_movement() -> None:
    # Centre y: 0.50 → 0.60, x unchanged → movement 0.10
    frames = [
        _hips(0, (0.40, 0.50), (0.60, 0.50)),
        _hips(1, (0.40, 0.60), (0.60, 0.60)),
    ]
    motion = diagnose_pose_frames(frames).hip_centre_motion

    assert motion.pair_count == 1
    _assert_finite_motion(motion)
    assert motion.mean_normalized_displacement == pytest.approx(0.10)


def test_diagonal_normalized_hip_movement_is_euclidean() -> None:
    # Centre (0.50, 0.50) → (0.80, 0.90) → hypot(0.30, 0.40) = 0.50
    frames = [
        _hips(0, (0.40, 0.50), (0.60, 0.50)),
        _hips(1, (0.70, 0.90), (0.90, 0.90)),
    ]
    motion = diagnose_pose_frames(frames).hip_centre_motion

    assert motion.pair_count == 1
    _assert_finite_motion(motion)
    assert motion.mean_normalized_displacement == pytest.approx(0.50)


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920), (640, 480)])
def test_normalized_hip_movement_is_independent_of_image_resolution(size: tuple[int, int]) -> None:
    width, height = size
    frames = [
        _hips(0, (0.40, 0.50), (0.60, 0.50), width=width, height=height),
        _hips(1, (0.50, 0.50), (0.70, 0.50), width=width, height=height),
    ]
    motion = diagnose_pose_frames(frames).hip_centre_motion

    assert motion.pair_count == 1
    _assert_finite_motion(motion)
    assert motion.mean_normalized_displacement == pytest.approx(0.10)


def test_hip_centre_does_not_bridge_a_missing_pose() -> None:
    frames = [
        _pose_frame(0),
        _empty_frame(1),
        _pose_frame(2),
    ]

    motion = diagnose_pose_frames(frames).hip_centre_motion

    assert motion.pair_count == 0
    assert motion.mean_normalized_displacement is None


def test_hip_centre_skips_frames_missing_a_hip() -> None:
    no_right_hip = _pose_frame(1, {"left_hip": _landmark("left_hip", 0.5, 0.5)})
    frames = [_pose_frame(0), no_right_hip, _pose_frame(2)]

    motion = diagnose_pose_frames(frames).hip_centre_motion
    assert motion.pair_count == 0
    assert motion.mean_normalized_displacement is None


def test_out_of_order_frames_are_rejected() -> None:
    with pytest.raises(QualityDiagnosticsError, match="increasing"):
        diagnose_pose_frames([_pose_frame(2), _pose_frame(1)])


def test_mixed_image_sizes_are_rejected() -> None:
    with pytest.raises(QualityDiagnosticsError, match="same image size"):
        diagnose_pose_frames([_pose_frame(0, width=200), _pose_frame(1, width=400)])


def test_diagnostics_have_no_pass_fail_fields() -> None:
    result = diagnose_pose_frames([_pose_frame(0)])

    assert isinstance(result, QualityDiagnostics)
    field_names = set(QualityDiagnostics.__dataclass_fields__) | set(
        type(result.hip_centre_motion).__dataclass_fields__
    )
    forbidden = {
        "pass",
        "fail",
        "accepted",
        "rejected",
        "verdict",
        "threshold",
        "score",
        "good",
        "bad",
    }
    assert field_names.isdisjoint(forbidden)
