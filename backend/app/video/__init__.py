"""Video reading with OpenCV. Independent of the web API."""

from app.video.reader import (
    VideoFrame,
    VideoMetadata,
    VideoReadError,
    iter_frames,
    read_video_metadata,
)

__all__ = [
    "VideoFrame",
    "VideoMetadata",
    "VideoReadError",
    "iter_frames",
    "read_video_metadata",
]
