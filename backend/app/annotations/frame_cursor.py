"""Exact frame stepping over a real video file.

Frames are decoded in order. Backward moves and jumps reopen the file and
decode from the start, because container seeking is not exact. The file is
only read, never written.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.video import VideoFrame, VideoMetadata, VideoReadError, read_video_metadata


class FrameCursor:
    """One decoded frame of a video, addressed by a zero-based index."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.metadata: VideoMetadata = read_video_metadata(self.path)
        self.index: int | None = None
        self.image: np.ndarray | None = None
        self.decoded_count: int | None = None
        self._capture: cv2.VideoCapture | None = None
        self._next_index = 0
        self._open_capture()

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def __enter__(self) -> "FrameCursor":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def timestamp_seconds(self) -> float | None:
        if self.index is None:
            return None
        return self.index / self.metadata.fps

    def current(self) -> VideoFrame:
        if self.index is None or self.image is None:
            raise VideoReadError(f"No frame is loaded from {self.path.name}.")
        return VideoFrame(
            index=self.index,
            timestamp_seconds=self.index / self.metadata.fps,
            image=self.image,
        )

    def goto(self, index: int) -> VideoFrame:
        """Decode ``index`` exactly. ``0`` is the first frame."""
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise VideoReadError(f"Frame index must be an integer >= 0, got {index!r}.")
        if self.decoded_count is not None and index >= self.decoded_count:
            raise VideoReadError(
                f"Frame {index} is past the decoded end of {self.path.name} "
                f"({self.decoded_count} frames)."
            )
        if self.index == index and self.image is not None:
            return self.current()
        if index < self._next_index:
            self._reopen()
        while self._next_index <= index:
            self._read_next()
        return self.current()

    def step(self, delta: int) -> bool:
        """Move by one decoded frame. Returns False at either end."""
        if delta not in (-1, 1):
            raise VideoReadError("Frame step must be -1 or 1.")
        if self.index is None:
            target = 0 if delta > 0 else -1
        else:
            target = self.index + delta
        if target < 0:
            return False
        try:
            self.goto(target)
        except VideoReadError:
            return False
        return True

    def _open_capture(self) -> None:
        capture = cv2.VideoCapture(str(self.path), cv2.CAP_FFMPEG)
        if not capture.isOpened():
            capture.release()
            raise VideoReadError(f"OpenCV could not open {self.path.name}.")
        self._capture = capture
        self._next_index = 0

    def _reopen(self) -> None:
        self.close()
        self.index = None
        self.image = None
        self._open_capture()

    def _read_next(self) -> None:
        if self._capture is None:
            raise VideoReadError(f"Video capture for {self.path.name} is closed.")
        decoded, image = self._capture.read()
        if not decoded or image is None:
            self.decoded_count = self._next_index
            raise VideoReadError(
                f"Frame {self._next_index} is past the decoded end of {self.path.name}."
            )
        self.index = self._next_index
        self.image = image.copy()
        self._next_index += 1
