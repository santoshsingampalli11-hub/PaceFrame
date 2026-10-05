"""The interface every pose estimator implements, and the video-to-pose loop."""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import numpy as np

from app.pose.landmarks import PoseFrame
from app.video import VideoFrame, iter_frames


class PoseEstimationError(Exception):
    """A pose estimator could not be created or failed while processing a frame."""


class PoseEstimator(Protocol):
    def estimate(self, frame: VideoFrame) -> PoseFrame:
        """Return the pose found in one decoded video frame."""
        ...


def estimate_video_poses(video_path: str | Path, estimator: PoseEstimator) -> Iterator[PoseFrame]:
    """Yield one ``PoseFrame`` per decoded frame of the video, in order."""
    for frame in iter_frames(video_path):
        yield estimator.estimate(frame)


def validate_frame_image(image: object) -> None:
    """Raise ``ValueError`` unless ``image`` is a non-empty uint8 BGR image."""
    if not isinstance(image, np.ndarray):
        raise ValueError(f"Frame image must be a NumPy array, got {type(image).__name__}.")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(
            f"Frame image must have shape (height, width, 3) in BGR order, got {image.shape}."
        )
    if image.shape[0] == 0 or image.shape[1] == 0:
        raise ValueError(f"Frame image is empty: shape {image.shape}.")
    if image.dtype != np.uint8:
        raise ValueError(f"Frame image must be uint8, got {image.dtype}.")
