"""Pose estimation with MediaPipe Pose Landmarker (MediaPipe Tasks API)."""

import math
from pathlib import Path
from types import TracebackType

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    PoseLandmarkerResult,
    RunningMode,
)

from app.pose.estimator import PoseEstimationError, validate_frame_image
from app.pose.landmarks import LANDMARK_NAMES, Landmark, PoseFrame
from app.video import VideoFrame

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/1/pose_landmarker_full.task"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "pose_landmarker_full.task"


class MediaPipePoseEstimator:
    """Runs MediaPipe Pose Landmarker on consecutive frames of one video.

    MediaPipe's video mode tracks the person from frame to frame, so frames
    must arrive in increasing timestamp order. Use a new estimator per video.
    """

    def __init__(self, model_path: str | Path = DEFAULT_MODEL_PATH) -> None:
        model_path = Path(model_path)
        if not model_path.is_file():
            raise PoseEstimationError(
                f"MediaPipe pose model not found at {model_path.name}. "
                f"Download it from {MODEL_URL} (see backend/README.md)."
            )
        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=RunningMode.VIDEO,
            num_poses=1,
        )
        try:
            self._landmarker: PoseLandmarker | None = PoseLandmarker.create_from_options(
                options
            )
        except (ValueError, RuntimeError) as error:
            raise PoseEstimationError(
                f"MediaPipe could not load the pose model {model_path.name}: {error}"
            ) from error
        self._last_timestamp_ms: int | None = None

    def estimate(self, frame: VideoFrame) -> PoseFrame:
        if self._landmarker is None:
            raise PoseEstimationError("This pose estimator has been closed.")
        validate_frame_image(frame.image)
        timestamp_ms = round(frame.timestamp_seconds * 1000)
        if self._last_timestamp_ms is not None and timestamp_ms <= self._last_timestamp_ms:
            raise PoseEstimationError(
                f"Frame {frame.index} has timestamp {timestamp_ms} ms, which is not after "
                f"the previous frame ({self._last_timestamp_ms} ms). Frames must be in order, "
                "and each video needs its own estimator."
            )

        rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        try:
            result = self._landmarker.detect_for_video(image, timestamp_ms)
        except (ValueError, RuntimeError) as error:
            raise PoseEstimationError(
                f"MediaPipe pose estimation failed on frame {frame.index}: {error}"
            ) from error

        self._last_timestamp_ms = timestamp_ms
        return pose_frame_from_result(result, frame)

    def close(self) -> None:
        if self._landmarker is None:
            return
        self._landmarker.close()
        self._landmarker = None

    def __enter__(self) -> "MediaPipePoseEstimator":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def pose_frame_from_result(result: PoseLandmarkerResult, frame: VideoFrame) -> PoseFrame:
    """Convert a MediaPipe result into the estimator-independent ``PoseFrame``."""
    height, width = frame.image.shape[:2]
    landmarks: dict[str, Landmark] = {}
    if result.pose_landmarks:
        detected = result.pose_landmarks[0]
        if len(detected) != len(LANDMARK_NAMES):
            raise PoseEstimationError(
                f"MediaPipe returned {len(detected)} landmarks on frame {frame.index}; "
                f"expected {len(LANDMARK_NAMES)}."
            )
        landmarks = {
            name: _landmark_from_mediapipe(name, point, frame.index)
            for name, point in zip(LANDMARK_NAMES, detected)
        }

    return PoseFrame(
        frame_index=frame.index,
        timestamp_seconds=frame.timestamp_seconds,
        image_width=width,
        image_height=height,
        landmarks=landmarks,
    )


def _landmark_from_mediapipe(name: str, point: object, frame_index: int) -> Landmark:
    x = getattr(point, "x", None)
    y = getattr(point, "y", None)
    if x is None or y is None or not math.isfinite(x) or not math.isfinite(y):
        raise PoseEstimationError(
            f"MediaPipe returned a non-finite {name} coordinate on frame {frame_index}."
        )
    return Landmark(
        name=name,
        x=float(x),
        y=float(y),
        visibility=_optional_score(getattr(point, "visibility", None)),
        presence=_optional_score(getattr(point, "presence", None)),
    )


def _optional_score(value: object) -> float | None:
    if value is None:
        return None
    score = float(value)
    if not math.isfinite(score):
        return None
    return score
