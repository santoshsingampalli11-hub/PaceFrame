"""Load a completed delivery session and check the stored video bytes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.api.session_store import (
    MANIFEST_NAME,
    SESSION_RECORD_NAME,
    InvalidSessionId,
    SessionRecord,
    SessionStoreError,
    load_session_record,
    resolve_session_dir,
)
from app.pilot.session_manifest import (
    PilotSessionManifest,
    SessionManifestError,
    load_session_manifest,
    verify_session_manifest,
)


class SessionNotFound(SessionStoreError):
    """The session id is well-formed but no completed session exists."""


class SessionNotVerified(SessionStoreError):
    """The session files exist but the video bytes do not match the manifest."""


@dataclass(frozen=True)
class VerifiedSession:
    """A completed upload whose stored video matches the manifest hash."""

    session_id: str
    session_dir: Path
    record: SessionRecord
    manifest: PilotSessionManifest
    video_path: Path


def load_completed_session(root: Path, session_id: str) -> VerifiedSession:
    """Resolve a session without hashing. Used for read-only status lookups."""
    try:
        session_dir = resolve_session_dir(root, session_id)
    except InvalidSessionId:
        raise
    record_path = session_dir / SESSION_RECORD_NAME
    manifest_path = session_dir / MANIFEST_NAME
    if not record_path.is_file() or not manifest_path.is_file():
        raise SessionNotFound("Session not found.")
    try:
        record = load_session_record(session_dir)
        manifest = load_session_manifest(manifest_path)
    except (SessionStoreError, SessionManifestError) as error:
        raise SessionNotFound("Session not found.") from error
    video_path = session_dir / record.stored_filename
    if record.session_id != session_id or not video_path.is_file():
        raise SessionNotFound("Session not found.")
    return VerifiedSession(session_id, session_dir, record, manifest, video_path)


def load_verified_session(root: Path, session_id: str) -> VerifiedSession:
    """Load a completed session and require the stored bytes to match the manifest.

    A matching hash is not scientific suitability.
    """
    session = load_completed_session(root, session_id)
    verification = verify_session_manifest(session.session_dir / MANIFEST_NAME, session.video_path)
    if not verification.ok:
        raise SessionNotVerified("Video does not match the session manifest.")
    return session
