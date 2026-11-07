"""Exact zero-based JPEG frames from an uploaded original video.

Frames come from the existing sequential reader. This module does not seek
with CAP_PROP_POS_FRAMES, does not run pose estimation, and does not serve
the original video file.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass

import cv2

from app.api.session_access import SessionNotVerified, VerifiedSession
from app.api.settings import get_settings
from app.pilot.session_manifest import verify_session_manifest
from app.video.reader import VideoFrame, VideoReadError, iter_frames

_MAX_CACHED_FRAMES = 16
_JPEG_QUALITY = 80

_lock = threading.Lock()
_slots: threading.BoundedSemaphore | None = None
_verified: dict[str, tuple[str, int, int]] = {}
_cache: OrderedDict[tuple[str, str, int], bytes] = OrderedDict()


@dataclass
class _DecodeCursor:
    """One open sequential read, positioned just after the last returned frame."""

    session_id: str
    sha256: str
    path: str
    next_index: int
    stream: Iterator[VideoFrame]


_cursor: _DecodeCursor | None = None


class FrameAccessError(ValueError):
    """The requested decoded frame cannot be returned."""


class FrameCapacityError(FrameAccessError):
    """Another frame decode is already using the local limit."""


def reset_frame_service() -> None:
    """Drop cached frames, the open decode, and the decode slot. Used by tests."""
    global _slots, _cursor
    with _lock:
        _slots = None
        _verified.clear()
        _cache.clear()
        cursor = _cursor
        _cursor = None
    if cursor is not None:
        _close_stream(cursor.stream)


def original_frame_jpeg(session: VerifiedSession, frame_index: int) -> bytes:
    """Return one exact decoded frame as JPEG bytes."""
    if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
        raise FrameAccessError("Invalid frame index.")
    if frame_index >= session.manifest.decoded_frame_count:
        raise FrameAccessError("That frame is outside the decoded video.")
    _require_verified(session)
    cache_key = (session.session_id, session.manifest.video_sha256, frame_index)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    if not _acquire_slot():
        raise FrameCapacityError("Frame decoding capacity is full.")
    try:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        jpeg = _decode_exact_jpeg(session, frame_index)
        _cache_put(cache_key, jpeg)
        return jpeg
    finally:
        _release_slot()


def _require_verified(session: VerifiedSession) -> None:
    stat = session.video_path.stat()
    identity = (session.manifest.video_sha256, stat.st_size, stat.st_mtime_ns)
    with _lock:
        if _verified.get(session.session_id) == identity:
            return
    verification = verify_session_manifest(session.session_dir / "manifest.json", session.video_path)
    if not verification.ok:
        with _lock:
            _verified.pop(session.session_id, None)
            _drop_session_cache(session.session_id)
            _drop_cursor(session.session_id)
        raise SessionNotVerified("Video does not match the session manifest.")
    stat_after = session.video_path.stat()
    confirmed = (session.manifest.video_sha256, stat_after.st_size, stat_after.st_mtime_ns)
    with _lock:
        _verified[session.session_id] = confirmed


def _decode_exact_jpeg(session: VerifiedSession, frame_index: int) -> bytes:
    stream, expected = _open_stream(session, frame_index)
    previous: tuple[int, bytes] | None = None
    held = False
    try:
        for frame in stream:
            if frame.index != expected:
                raise FrameAccessError("Decoded frame index did not match the sequential position.")
            if frame.index == frame_index:
                jpeg = _encode_jpeg(frame.image)
                if previous is not None:
                    _cache_put((session.session_id, session.manifest.video_sha256, previous[0]), previous[1])
                _hold_cursor(session, stream, frame.index + 1)
                held = True
                return jpeg
            if frame.index + 1 == frame_index:
                previous = (frame.index, _encode_jpeg(frame.image))
            expected += 1
        raise FrameAccessError("That decoded frame is not available.")
    except VideoReadError as error:
        raise FrameAccessError("The video frame could not be decoded.") from error
    finally:
        if not held:
            _close_stream(stream)


def _acquire_slot() -> bool:
    return _semaphore().acquire(blocking=False)


def _release_slot() -> None:
    _semaphore().release()


def _semaphore() -> threading.BoundedSemaphore:
    global _slots
    with _lock:
        if _slots is None:
            limit = get_settings().max_frame_decodes
            if limit < 1:
                limit = 1
            _slots = threading.BoundedSemaphore(limit)
        return _slots


def _cache_get(key: tuple[str, str, int]) -> bytes | None:
    with _lock:
        value = _cache.get(key)
        if value is None:
            return None
        _cache.move_to_end(key)
        return value


def _cache_put(key: tuple[str, str, int], jpeg: bytes) -> None:
    with _lock:
        _cache[key] = jpeg
        _cache.move_to_end(key)
        while len(_cache) > _MAX_CACHED_FRAMES:
            _cache.popitem(last=False)


def _encode_jpeg(image: object) -> bytes:
    encoded, jpeg = cv2.imencode(
        ".jpg",
        image,
        [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY],
    )
    if not encoded:
        raise FrameAccessError("The decoded frame could not be encoded.")
    return jpeg.tobytes()


def _open_stream(session: VerifiedSession, frame_index: int) -> tuple[Iterator[VideoFrame], int]:
    global _cursor
    with _lock:
        cursor = _cursor
        reusable = (
            cursor is not None
            and cursor.session_id == session.session_id
            and cursor.sha256 == session.manifest.video_sha256
            and cursor.path == str(session.video_path)
            and cursor.next_index <= frame_index
        )
        if reusable and cursor is not None:
            _cursor = None
            return cursor.stream, cursor.next_index
        _cursor = None
    if cursor is not None:
        _close_stream(cursor.stream)
    return iter_frames(session.video_path), 0


def _hold_cursor(session: VerifiedSession, stream: Iterator[VideoFrame], next_index: int) -> None:
    global _cursor
    with _lock:
        if _cursor is not None:
            _close_stream(_cursor.stream)
        _cursor = _DecodeCursor(
            session_id=session.session_id,
            sha256=session.manifest.video_sha256,
            path=str(session.video_path),
            next_index=next_index,
            stream=stream,
        )


def _drop_cursor(session_id: str) -> None:
    """Caller must hold ``_lock``. The stream is closed after the lock is released by reset paths."""
    global _cursor
    if _cursor is not None and _cursor.session_id == session_id:
        stream = _cursor.stream
        _cursor = None
        _close_stream(stream)


def _close_stream(stream: Iterator[VideoFrame]) -> None:
    close = getattr(stream, "close", None)
    if close is not None:
        close()


def _drop_session_cache(session_id: str) -> None:
    for key in [item for item in _cache if item[0] == session_id]:
        _cache.pop(key, None)
