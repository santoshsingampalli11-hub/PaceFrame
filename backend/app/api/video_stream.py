"""Stream one verified session video without loading it into memory.

The file is the server-stored upload (video.mp4, video.mov, or video.avi).
Callers cannot choose a path. A matching hash is not scientific suitability.
This route does not transcode and does not run pose estimation.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from app.api.session_access import SessionNotVerified, VerifiedSession
from app.api.session_store import ALLOWED_STORED_FILENAMES
from app.pilot.session_manifest import verify_session_manifest

CHUNK_BYTES = 64 * 1024
MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
}

_SINGLE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$", re.IGNORECASE)
_lock = threading.Lock()
_verified: dict[str, tuple[str, int, int]] = {}


class RangeNotSatisfiable(ValueError):
    """The Range header does not select bytes inside the file."""


class RangeNotSupported(ValueError):
    """The Range header is malformed or asks for multiple ranges."""


@dataclass(frozen=True)
class ByteSpan:
    """Inclusive byte interval inside a file."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def reset_video_stream_cache() -> None:
    """Drop remembered file identities. Used by tests."""
    with _lock:
        _verified.clear()


def media_type_for_filename(filename: str) -> str:
    """Return the container type for a stored upload name."""
    suffix = Path(filename).suffix.lower()
    try:
        return MEDIA_TYPES[suffix]
    except KeyError as error:
        raise ValueError("Stored video type is not supported.") from error


def verified_video_size(session: VerifiedSession) -> int:
    """Return the size of the session video after a hash check.

    The hash is repeated when the file size or modification time changes.
    Unchanged files are not hashed again.
    """
    path = _stored_video(session)
    stat = path.stat()
    identity = (session.manifest.video_sha256, stat.st_size, stat.st_mtime_ns)
    with _lock:
        if _verified.get(session.session_id) == identity:
            return stat.st_size
    verification = verify_session_manifest(session.session_dir / "manifest.json", path)
    if not verification.ok:
        with _lock:
            _verified.pop(session.session_id, None)
        raise SessionNotVerified("Video does not match the session manifest.")
    stat_after = path.stat()
    confirmed = (session.manifest.video_sha256, stat_after.st_size, stat_after.st_mtime_ns)
    with _lock:
        _verified[session.session_id] = confirmed
    return stat_after.st_size


def parse_byte_range(header: str | None, total: int) -> ByteSpan | None:
    """Parse one ``bytes=`` range. ``None`` means the whole file.

    Multiple ranges are not supported. Ends past the file are clipped.
    A start at or past the end is not satisfiable.
    """
    if header is None or header.strip() == "":
        if total < 0:
            raise RangeNotSatisfiable("The video has no readable length.")
        return None
    value = header.strip()
    if "," in value:
        raise RangeNotSupported("Multiple ranges are not supported.")
    match = _SINGLE_RANGE.fullmatch(value)
    if match is None:
        raise RangeNotSupported("The range is not a single bytes range.")
    start_text, end_text = match.group(1), match.group(2)
    if start_text == "" and end_text == "":
        raise RangeNotSupported("The range is not a single bytes range.")
    if total < 0:
        raise RangeNotSatisfiable("The video has no readable length.")
    if total == 0:
        raise RangeNotSatisfiable("The video is empty.")
    if start_text == "":
        suffix = int(end_text)
        if suffix <= 0:
            raise RangeNotSatisfiable("The suffix range is empty.")
        start = max(total - suffix, 0)
        return ByteSpan(start, total - 1)
    start = int(start_text)
    if start >= total:
        raise RangeNotSatisfiable("The range starts past the end of the video.")
    if end_text == "":
        return ByteSpan(start, total - 1)
    end = int(end_text)
    if end < start:
        raise RangeNotSatisfiable("The range end is before the start.")
    return ByteSpan(start, min(end, total - 1))


def iter_file_span(path: Path, start: int, end: int) -> Iterator[bytes]:
    """Yield at most ``CHUNK_BYTES`` at a time from an inclusive interval."""
    remaining = end - start + 1
    handle = path.open("rb")
    try:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        handle.close()


def _stored_video(session: VerifiedSession) -> Path:
    filename = session.video_path.name
    if filename not in ALLOWED_STORED_FILENAMES:
        raise SessionNotVerified("Video does not match the session manifest.")
    resolved = session.video_path.resolve()
    if resolved.parent != session.session_dir.resolve():
        raise SessionNotVerified("Video does not match the session manifest.")
    if not resolved.is_file():
        raise SessionNotVerified("Video does not match the session manifest.")
    return resolved
