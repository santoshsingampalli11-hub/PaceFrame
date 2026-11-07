"""Isolated on-disk storage for uploaded delivery sessions.

Session directories live under a configured ignored folder. Absolute paths
are not stored in session records and are not returned to API callers.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
STORED_VIDEO_STEM = "video"
SESSION_RECORD_NAME = "session.json"
MANIFEST_NAME = "manifest.json"
SESSION_STATUS_CREATED = "created"
UPLOAD_CHUNK_BYTES = 64 * 1024
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi"}
ALLOWED_STORED_FILENAMES = {f"{STORED_VIDEO_STEM}{suffix}" for suffix in ALLOWED_VIDEO_EXTENSIONS}
ALLOWED_ORIENTATIONS = {"landscape", "portrait", "square"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".jar", ".war"}
_ALLOCATE_ATTEMPTS = 8


class SessionStoreError(ValueError):
    """The session directory could not be used."""


class InvalidSessionId(SessionStoreError):
    """The session id is not an opaque identifier."""


class UploadLimitExceeded(SessionStoreError):
    """The upload exceeded the configured byte limit."""


class DuplicateSessionError(SessionStoreError):
    """A session directory with that id already exists."""


@dataclass(frozen=True)
class SessionRecord:
    """API metadata for a finished upload. It is not the scientific manifest."""

    session_id: str
    status: str
    stored_filename: str
    orientation: str


def allocate_session_dir(root: Path) -> tuple[str, Path]:
    """Create an empty unique session directory. Existing directories are left alone."""
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise SessionStoreError("Session storage is not available.")
    for _attempt in range(_ALLOCATE_ATTEMPTS):
        session_id = secrets.token_hex(16)
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            continue
        session_dir = root / session_id
        try:
            session_dir.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        except OSError as error:
            raise SessionStoreError("Session storage is not available.") from error
        return session_id, session_dir
    raise DuplicateSessionError("Could not allocate a unique session id.")


def resolve_session_dir(root: Path, session_id: str) -> Path:
    """Return the session directory if ``session_id`` is a single opaque component."""
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise InvalidSessionId("Invalid session id.")
    root_resolved = root.resolve()
    candidate = (root_resolved / session_id).resolve()
    if candidate.parent != root_resolved:
        raise InvalidSessionId("Invalid session id.")
    return candidate


def stored_video_filename(extension: str) -> str:
    """Return the server-controlled video file name for an allowed extension."""
    suffix = extension.lower()
    if suffix not in ALLOWED_VIDEO_EXTENSIONS:
        raise SessionStoreError("Unsupported video format.")
    return f"{STORED_VIDEO_STEM}{suffix}"


def client_filename(raw_name: str | None) -> str:
    """Keep only the final path component of an upload file name."""
    if raw_name is None:
        raise SessionStoreError("Video file name is missing.")
    normalized = str(raw_name).replace("\\", "/").strip()
    name = Path(normalized).name
    if not name or name in {".", ".."}:
        raise SessionStoreError("Video file name is missing.")
    if any(character in name for character in '<>:"|?*') or any(ord(character) < 32 for character in name):
        raise SessionStoreError("Video file name is invalid.")
    return name


def extension_for_filename(filename: str) -> str:
    """Return a lower-case suffix, or empty if the name has no extension."""
    return Path(filename).suffix.lower()


def is_allowed_video_extension(extension: str) -> bool:
    return extension in ALLOWED_VIDEO_EXTENSIONS


def is_archive_extension(extension: str) -> bool:
    return extension in ARCHIVE_EXTENSIONS


async def save_upload_limited(
    upload: Any,
    destination: Path,
    max_bytes: int,
    chunk_bytes: int = UPLOAD_CHUNK_BYTES,
) -> int:
    """Copy upload bytes in bounded chunks. The destination is not overwritten."""
    if max_bytes <= 0:
        raise SessionStoreError("Upload limit is not configured.")
    if destination.exists():
        raise SessionStoreError("The stored video already exists. It was not overwritten.")
    if chunk_bytes <= 0:
        raise SessionStoreError("Upload chunk size is invalid.")
    part_path = destination.with_name(destination.name + ".part")
    written = 0
    try:
        with part_path.open("wb") as handle:
            while True:
                chunk = await upload.read(chunk_bytes)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise UploadLimitExceeded("Upload exceeds the configured size limit.")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if destination.exists():
            raise SessionStoreError("The stored video already exists. It was not overwritten.")
        os.replace(part_path, destination)
        return written
    finally:
        if part_path.exists():
            part_path.unlink(missing_ok=True)


def write_json_exclusive(path: Path, payload: dict[str, object]) -> None:
    """Write JSON once. An existing file is left unchanged."""
    if path.exists():
        raise SessionStoreError(f"{path.name} already exists. It was not overwritten.")
    temp_path: Path | None = None
    try:
        handle, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if path.exists():
            raise SessionStoreError(f"{path.name} already exists. It was not overwritten.")
        os.replace(temp_path, path)
        temp_path = None
    except OSError as error:
        raise SessionStoreError(f"Could not write {path.name}.") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def write_json_replace(path: Path, payload: dict[str, object]) -> None:
    """Replace JSON via a temporary file in the same directory."""
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, path)
        temp_path = None
    except OSError as error:
        raise SessionStoreError(f"Could not write {path.name}.") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def write_session_record(session_dir: Path, record: SessionRecord) -> None:
    """Write the API session record. Absolute paths are not stored."""
    write_json_exclusive(
        session_dir / SESSION_RECORD_NAME,
        {
            "session_id": record.session_id,
            "status": record.status,
            "stored_filename": record.stored_filename,
            "orientation": record.orientation,
        },
    )


def load_session_record(session_dir: Path) -> SessionRecord:
    """Read the API session record from a resolved session directory."""
    path = session_dir / SESSION_RECORD_NAME
    if not path.is_file():
        raise SessionStoreError("Session not found.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SessionStoreError("Session not found.") from error
    if not isinstance(payload, dict):
        raise SessionStoreError("Session not found.")
    session_id = payload.get("session_id")
    status = payload.get("status")
    stored_filename = payload.get("stored_filename")
    orientation = payload.get("orientation")
    if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
        raise SessionStoreError("Session not found.")
    if status != SESSION_STATUS_CREATED:
        raise SessionStoreError("Session not found.")
    if stored_filename not in ALLOWED_STORED_FILENAMES:
        raise SessionStoreError("Session not found.")
    if orientation not in ALLOWED_ORIENTATIONS:
        raise SessionStoreError("Session not found.")
    return SessionRecord(
        session_id=session_id,
        status=status,
        stored_filename=stored_filename,
        orientation=orientation,
    )


def remove_session_dir(root: Path, session_dir: Path) -> None:
    """Delete one session directory if and only if it is a direct child of ``root``."""
    try:
        root_resolved = root.resolve()
        directory = session_dir.resolve()
    except OSError:
        return
    if directory.parent != root_resolved or directory == root_resolved:
        return
    if not SESSION_ID_PATTERN.fullmatch(directory.name):
        return
    shutil.rmtree(directory, ignore_errors=True)
