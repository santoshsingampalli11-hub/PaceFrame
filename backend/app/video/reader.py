"""Open video files with OpenCV and read their metadata and frames."""

import logging
import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("fast_bowling.video")


class VideoReadError(Exception):
    """A video file exists but cannot be opened, described, or decoded."""


@dataclass(frozen=True)
class VideoMetadata:
    width: int
    height: int
    fps: float
    frame_count: int

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps


@dataclass(frozen=True)
class VideoFrame:
    index: int
    timestamp_seconds: float
    # BGR, uint8, shape (height, width, 3), exactly as decoded by OpenCV.
    image: np.ndarray


def read_video_metadata(path: str | Path) -> VideoMetadata:
    """Return the metadata of a video after confirming its first frame decodes."""
    video_path = Path(path)
    capture = _open_capture(video_path)
    try:
        metadata = _read_metadata(capture, video_path)
        decoded, _ = capture.read()
        if not decoded:
            raise VideoReadError(
                f"OpenCV opened {video_path.name} but could not decode its first frame."
            )
        return metadata
    finally:
        capture.release()


def iter_frames(path: str | Path) -> Iterator[VideoFrame]:
    """Yield every decodable frame of a video in order.

    Errors are raised when iteration starts, not when this function is called.
    Timestamps are ``index / fps``, which assumes a constant frame rate.
    """
    video_path = Path(path)
    capture = _open_capture(video_path)
    try:
        metadata = _read_metadata(capture, video_path)
        index = 0
        while True:
            decoded, image = capture.read()
            if not decoded:
                break
            yield VideoFrame(
                index=index,
                timestamp_seconds=index / metadata.fps,
                image=image,
            )
            index += 1
        if index == 0:
            raise VideoReadError(
                f"OpenCV could not decode any frames from {video_path.name}."
            )
        if index != metadata.frame_count:
            logger.warning(
                "%s header reports %s frames but %s frames were decoded. "
                "Timestamps still use index / fps.",
                video_path.name,
                metadata.frame_count,
                index,
            )
    finally:
        capture.release()


def _open_capture(path: Path) -> cv2.VideoCapture:
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {path.name}")
    if not path.is_file():
        raise VideoReadError(f"{path.name} is not a file.")

    # Force the bundled FFmpeg backend so behaviour does not depend on which
    # OS-specific backend OpenCV would otherwise pick.
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    if not capture.isOpened():
        capture.release()
        raise VideoReadError(
            f"OpenCV could not open {path.name}. The file may be corrupt, not a video, "
            "or use a container/codec that OpenCV's FFmpeg backend cannot decode."
        )
    return capture


def _read_metadata(capture: cv2.VideoCapture, path: Path) -> VideoMetadata:
    width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)

    if not (_is_positive(width) and _is_positive(height)):
        raise VideoReadError(
            f"{path.name} reports an invalid frame size: {width} x {height}."
        )
    if not _is_positive(fps):
        raise VideoReadError(
            f"{path.name} reports an invalid FPS ({fps}); "
            "frame timestamps and duration cannot be computed."
        )
    if not _is_positive(frame_count):
        raise VideoReadError(f"{path.name} reports an invalid frame count: {frame_count}.")

    return VideoMetadata(
        width=int(width),
        height=int(height),
        fps=fps,
        frame_count=int(frame_count),
    )


def _is_positive(value: float) -> bool:
    return math.isfinite(value) and value > 0
