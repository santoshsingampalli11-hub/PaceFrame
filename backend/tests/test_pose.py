"""Tests for the pose-estimation module.

Most tests need no person in the image: they use blank/synthetic frames or a
hand-built MediaPipe result. Tests that run the real model are skipped if the
model file has not been downloaded (see README). The real-video test only runs
when POSE_TEST_VIDEO points at a local video; it checks that the pipeline runs,
not that the pose is accurate.
"""

import math
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from mediapipe.tasks.python.components.containers.landmark import NormalizedLandmark
from mediapipe.tasks.python.vision import PoseLandmark, PoseLandmarkerResult

from app.pose import (
    LANDMARK_NAMES,
    SKELETON_CONNECTIONS,
    Landmark,
    PoseEstimationError,
    PoseFrame,
    estimate_video_poses,
)
from app.pose.debug import draw_pose, write_debug_video
from app.pose.mediapipe_estimator import (
    DEFAULT_MODEL_PATH,
    MediaPipePoseEstimator,
    pose_frame_from_result,
)
from app.video import VideoFrame

BACKEND_DIR = Path(__file__).resolve().parents[1]
WIDTH = 640
HEIGHT = 480

requires_model = pytest.mark.skipif(
    not DEFAULT_MODEL_PATH.is_file(),
    reason=f"MediaPipe pose model not downloaded to {DEFAULT_MODEL_PATH}",
)


def blank_frame(index: int = 0, fps: float = 30.0) -> VideoFrame:
    return VideoFrame(
        index=index,
        timestamp_seconds=index / fps,
        image=np.zeros((HEIGHT, WIDTH, 3), np.uint8),
    )


def synthetic_result() -> PoseLandmarkerResult:
    points = [
        NormalizedLandmark(
            x=0.2 + index / 100,
            y=0.1 + index / 50,
            z=0.0,
            visibility=index / 40,
            presence=1 - index / 40,
        )
        for index in range(len(LANDMARK_NAMES))
    ]
    return PoseLandmarkerResult(pose_landmarks=[points], pose_world_landmarks=[])


@pytest.fixture
def estimator():
    with MediaPipePoseEstimator() as pose_estimator:
        yield pose_estimator


# --- Estimator-independent representation --------------------------------


def test_landmark_names_follow_mediapipe_order() -> None:
    assert len(LANDMARK_NAMES) == len(PoseLandmark)
    for landmark in PoseLandmark:
        assert LANDMARK_NAMES[landmark.value] == landmark.name.lower()


def test_skeleton_only_uses_known_landmarks() -> None:
    known = set(LANDMARK_NAMES)
    for start, end in SKELETON_CONNECTIONS:
        assert start in known and end in known


def test_pose_module_needs_neither_fastapi_nor_mediapipe() -> None:
    check = (
        "import sys, app.pose; "
        "assert 'fastapi' not in sys.modules, 'fastapi imported'; "
        "assert 'mediapipe' not in sys.modules, 'mediapipe imported'; "
        "import app.pose.mediapipe_estimator; "
        "assert 'fastapi' not in sys.modules, 'fastapi imported by estimator'"
    )
    completed = subprocess.run(
        [sys.executable, "-c", check], cwd=BACKEND_DIR, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr


# --- MediaPipe result conversion (no model needed) -----------------------


def test_detected_pose_structure() -> None:
    frame = blank_frame(index=120, fps=30.0)

    pose = pose_frame_from_result(synthetic_result(), frame)

    assert pose.pose_detected
    assert pose.frame_index == 120
    assert pose.timestamp_seconds == pytest.approx(4.0)
    assert (pose.image_width, pose.image_height) == (WIDTH, HEIGHT)
    assert list(pose.landmarks) == list(LANDMARK_NAMES)

    left_knee = pose.landmarks["left_knee"]
    index = PoseLandmark.LEFT_KNEE.value
    assert left_knee.name == "left_knee"
    assert left_knee.x == pytest.approx(0.2 + index / 100)
    assert left_knee.y == pytest.approx(0.1 + index / 50)
    assert left_knee.visibility == pytest.approx(index / 40)
    assert left_knee.presence == pytest.approx(1 - index / 40)
    assert pose.pixel_xy("left_knee") == pytest.approx(
        (left_knee.x * WIDTH, left_knee.y * HEIGHT)
    )


def test_pixel_xy_uses_image_size_not_normalized_scale() -> None:
    pose = PoseFrame(
        frame_index=0,
        timestamp_seconds=0.0,
        image_width=1920,
        image_height=1080,
        landmarks={
            "left_knee": Landmark(name="left_knee", x=0.25, y=0.50, visibility=1.0, presence=1.0)
        },
    )

    assert pose.pixel_xy("left_knee") == pytest.approx((480.0, 540.0))


def test_pixel_xy_missing_landmark() -> None:
    pose = PoseFrame(
        frame_index=3, timestamp_seconds=0.1, image_width=WIDTH, image_height=HEIGHT, landmarks={}
    )

    with pytest.raises(KeyError, match="left_knee"):
        pose.pixel_xy("left_knee")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_landmark_rejects_non_finite_coordinates(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        Landmark(name="nose", x=value, y=0.5, visibility=1.0, presence=1.0)
    with pytest.raises(ValueError, match="finite"):
        Landmark(name="nose", x=0.5, y=value, visibility=1.0, presence=1.0)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_landmark_rejects_non_finite_scores(value: float) -> None:
    with pytest.raises(ValueError, match="visibility"):
        Landmark(name="nose", x=0.5, y=0.5, visibility=value, presence=None)
    with pytest.raises(ValueError, match="presence"):
        Landmark(name="nose", x=0.5, y=0.5, visibility=None, presence=value)


def test_landmark_does_not_clamp_coordinates_outside_unit_square() -> None:
    landmark = Landmark(name="nose", x=-0.1, y=1.2, visibility=None, presence=None)
    assert landmark.x == pytest.approx(-0.1)
    assert landmark.y == pytest.approx(1.2)


def test_landmarks_outside_unit_square_are_preserved() -> None:
    frame = blank_frame()
    points = [
        NormalizedLandmark(x=-0.1 if index == 0 else 1.2, y=0.5, visibility=0.9, presence=0.8)
        for index in range(len(LANDMARK_NAMES))
    ]
    result = PoseLandmarkerResult(pose_landmarks=[points], pose_world_landmarks=[])

    pose = pose_frame_from_result(result, frame)

    assert pose.landmarks["nose"].x == pytest.approx(-0.1)
    assert pose.landmarks["left_eye_inner"].x == pytest.approx(1.2)


def test_missing_visibility_is_preserved() -> None:
    frame = blank_frame()
    points = [
        NormalizedLandmark(x=0.4, y=0.5, visibility=None, presence=None)
        for _ in LANDMARK_NAMES
    ]
    result = PoseLandmarkerResult(pose_landmarks=[points], pose_world_landmarks=[])

    pose = pose_frame_from_result(result, frame)

    assert pose.landmarks["left_knee"].visibility is None
    assert pose.landmarks["left_knee"].presence is None


def test_non_finite_landmark_is_rejected() -> None:
    frame = blank_frame()
    points = [NormalizedLandmark(x=0.4, y=0.5) for _ in LANDMARK_NAMES]
    points[0] = NormalizedLandmark(x=float("nan"), y=0.5)
    result = PoseLandmarkerResult(pose_landmarks=[points], pose_world_landmarks=[])

    with pytest.raises(PoseEstimationError, match="non-finite"):
        pose_frame_from_result(result, frame)


def test_empty_result_means_no_pose() -> None:
    result = PoseLandmarkerResult(pose_landmarks=[], pose_world_landmarks=[])

    pose = pose_frame_from_result(result, blank_frame(index=7))

    assert not pose.pose_detected
    assert pose.landmarks == {}
    assert pose.frame_index == 7


def test_unexpected_landmark_count_is_rejected() -> None:
    result = PoseLandmarkerResult(
        pose_landmarks=[[NormalizedLandmark(x=0.5, y=0.5)] * 17], pose_world_landmarks=[]
    )

    with pytest.raises(PoseEstimationError, match="17 landmarks"):
        pose_frame_from_result(result, blank_frame())


# --- MediaPipe estimator ---------------------------------------------------


def test_missing_model_file(tmp_path: Path) -> None:
    with pytest.raises(PoseEstimationError, match="model not found"):
        MediaPipePoseEstimator(tmp_path / "missing.task")


def test_invalid_model_file(tmp_path: Path) -> None:
    model = tmp_path / "broken.task"
    model.write_bytes(b"not a model" * 100)

    with pytest.raises(PoseEstimationError, match="could not load the pose model"):
        MediaPipePoseEstimator(model)


@requires_model
def test_frame_without_person_has_no_pose(estimator: MediaPipePoseEstimator) -> None:
    frame = blank_frame(index=3)

    pose = estimator.estimate(frame)

    assert not pose.pose_detected
    assert pose.landmarks == {}
    assert pose.frame_index == 3
    assert pose.timestamp_seconds == frame.timestamp_seconds
    assert (pose.image_width, pose.image_height) == (WIDTH, HEIGHT)


@requires_model
def test_synthetic_noise_image_is_processed(estimator: MediaPipePoseEstimator) -> None:
    rng = np.random.default_rng(seed=0)
    frame = VideoFrame(
        index=0,
        timestamp_seconds=0.0,
        image=rng.integers(0, 256, (HEIGHT, WIDTH, 3), dtype=np.uint8),
    )

    pose = estimator.estimate(frame)

    assert isinstance(pose, PoseFrame)
    assert pose.landmarks == {} or list(pose.landmarks) == list(LANDMARK_NAMES)


@requires_model
@pytest.mark.parametrize(
    ("image", "message"),
    [
        (np.zeros((HEIGHT, WIDTH), np.uint8), "shape"),
        (np.zeros((HEIGHT, WIDTH, 4), np.uint8), "shape"),
        (np.zeros((0, WIDTH, 3), np.uint8), "empty"),
        (np.zeros((HEIGHT, WIDTH, 3), np.float32), "uint8"),
        ([[0, 0, 0]], "NumPy array"),
    ],
    ids=["grayscale", "four-channel", "empty", "float", "not-an-array"],
)
def test_invalid_frame_images_are_rejected(
    estimator: MediaPipePoseEstimator, image: object, message: str
) -> None:
    frame = VideoFrame(index=0, timestamp_seconds=0.0, image=image)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=message):
        estimator.estimate(frame)


@requires_model
def test_out_of_order_frames_are_rejected(estimator: MediaPipePoseEstimator) -> None:
    estimator.estimate(blank_frame(index=5))

    with pytest.raises(PoseEstimationError, match="not after the previous frame"):
        estimator.estimate(blank_frame(index=5))


@requires_model
def test_video_pipeline_preserves_index_and_timestamp(tmp_path: Path) -> None:
    fps = 10.0
    frame_count = 5
    path = tmp_path / "blank.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (WIDTH, HEIGHT))
    assert writer.isOpened()
    for _ in range(frame_count):
        writer.write(np.zeros((HEIGHT, WIDTH, 3), np.uint8))
    writer.release()

    with MediaPipePoseEstimator() as pose_estimator:
        poses = list(estimate_video_poses(path, pose_estimator))

    assert [pose.frame_index for pose in poses] == list(range(frame_count))
    for pose in poses:
        assert pose.timestamp_seconds == pytest.approx(pose.frame_index / fps)
        assert not pose.pose_detected


def test_rounded_millisecond_timestamps_increase_at_broadcast_frame_rates() -> None:
    """VIDEO-mode MediaPipe requires strictly increasing integer milliseconds."""
    for fps in (30000 / 1001, 60000 / 1001, 24.0, 25.0, 30.0, 50.0, 60.0, 120.0):
        stamps = [round((index / fps) * 1000) for index in range(3000)]
        assert all(
            later > earlier for earlier, later in zip(stamps, stamps[1:])
        ), f"non-increasing millisecond timestamps at {fps} fps"


# --- Debug drawing ---------------------------------------------------------


def test_draw_pose_draws_on_a_copy() -> None:
    frame = blank_frame(index=120)
    original = frame.image.copy()
    pose = pose_frame_from_result(synthetic_result(), frame)

    drawn = draw_pose(frame.image, pose)

    assert np.array_equal(frame.image, original)
    assert drawn.shape == original.shape
    x, y = pose.pixel_xy("left_knee")
    assert drawn[round(y), round(x)].any()


def test_draw_pose_labels_frames_without_pose() -> None:
    frame = blank_frame()
    pose = PoseFrame(
        frame_index=0, timestamp_seconds=0.0, image_width=WIDTH, image_height=HEIGHT, landmarks={}
    )

    drawn = draw_pose(frame.image, pose)

    assert drawn.any()


def test_draw_pose_rejects_mismatched_image_size() -> None:
    pose = pose_frame_from_result(synthetic_result(), blank_frame())

    with pytest.raises(ValueError, match="estimated on"):
        draw_pose(np.zeros((HEIGHT // 2, WIDTH // 2, 3), np.uint8), pose)


def test_draw_pose_handles_partial_landmarks() -> None:
    frame = blank_frame()
    pose = PoseFrame(
        frame_index=0,
        timestamp_seconds=0.0,
        image_width=WIDTH,
        image_height=HEIGHT,
        landmarks={
            "left_shoulder": Landmark("left_shoulder", 0.4, 0.3, 1.0, 1.0),
            "left_elbow": Landmark("left_elbow", 0.45, 0.45, None, None),
        },
    )

    drawn = draw_pose(frame.image, pose)

    assert drawn.shape == frame.image.shape
    assert drawn.any()


def test_write_debug_video_refuses_to_overwrite_input(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not used")

    with pytest.raises(ValueError, match="must not be the same"):
        write_debug_video(video, video)


@requires_model
def test_estimator_close_is_idempotent() -> None:
    estimator = MediaPipePoseEstimator()
    estimator.close()
    estimator.close()

    with pytest.raises(PoseEstimationError, match="has been closed"):
        estimator.estimate(blank_frame())


@requires_model
def test_repeated_sequential_frames(estimator: MediaPipePoseEstimator) -> None:
    poses = [estimator.estimate(blank_frame(index=index)) for index in range(3)]

    assert [pose.frame_index for pose in poses] == [0, 1, 2]
    assert all(not pose.pose_detected for pose in poses)


@requires_model
def test_write_debug_video_does_not_change_input(tmp_path: Path) -> None:
    fps = 10.0
    source = tmp_path / "blank.avi"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), fps, (WIDTH, HEIGHT))
    assert writer.isOpened()
    for _ in range(3):
        writer.write(np.zeros((HEIGHT, WIDTH, 3), np.uint8))
    writer.release()
    original = source.read_bytes()
    output = tmp_path / "overlay.mp4"

    stats = write_debug_video(source, output)

    assert source.read_bytes() == original
    assert output.is_file()
    assert stats.frame_count == 3
    assert stats.frames_with_pose == 0
    assert stats.longest_run_without_pose == 3


# --- Optional real-video run (not validation) ----------------------------


@requires_model
@pytest.mark.real_video
@pytest.mark.skipif("POSE_TEST_VIDEO" not in os.environ, reason="POSE_TEST_VIDEO not set")
def test_real_video_runs_through_pipeline() -> None:
    """REAL-WORLD STRESS TEST — not scientific validation, training data, or ground truth."""
    with MediaPipePoseEstimator() as pose_estimator:
        poses = list(estimate_video_poses(os.environ["POSE_TEST_VIDEO"], pose_estimator))

    detected = [pose for pose in poses if pose.pose_detected]
    assert detected, "MediaPipe did not detect a pose in any frame"
    for pose in detected:
        assert list(pose.landmarks) == list(LANDMARK_NAMES)
        for landmark in pose.landmarks.values():
            assert math.isfinite(landmark.x) and math.isfinite(landmark.y)
