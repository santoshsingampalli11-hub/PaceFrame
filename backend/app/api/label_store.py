"""Session-local phase labels using the canonical CSV writer and filename sidecar."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.annotations.models import AnnotationError, PhaseLabel, validate_phase_labels
from app.annotations.phase_labels import read_phase_labels, write_phase_labels
from app.annotations.video_identity import lookup_video_filename, remember_video_filename, video_identity_path
from app.api.session_access import VerifiedSession
from app.api.session_store import MANIFEST_NAME, SessionStoreError, write_json_exclusive, write_json_replace
from app.pilot.session_manifest import SessionManifestError, set_manifest_front_leg

LABELS_NAME = "phase_labels.csv"
LABELS_META_NAME = "labels_meta.json"
ANNOTATION_PROVENANCE = "human_confirmed_filename_sidecar"


class LabelConflictError(SessionStoreError):
    """Existing labels would be overwritten without an explicit replace."""


class FrontLegConflictError(SessionStoreError):
    """The manifest already records a different anatomical front leg."""


@dataclass(frozen=True)
class StoredLabels:
    """Safe label summary. Absolute paths are not included."""

    session_id: str
    bowler_id: str
    delivery_id: str
    video_filename: str
    bfc_frame: int | None
    ffc_frame: int | None
    release_frame: int | None
    labeler: str
    notes: str
    front_leg: str
    confirm_front_leg: bool
    confirm_label_link: bool
    annotation_provenance: str
    annotation_byte_identity_verified: bool


def labels_path(session_dir: Path) -> Path:
    return session_dir / LABELS_NAME


def save_session_labels(
    session: VerifiedSession,
    *,
    bfc_frame: int | None,
    ffc_frame: int,
    release_frame: int,
    front_leg: str,
    confirm_front_leg: bool,
    confirm_label_link: bool,
    labeler: str,
    notes: str,
    replace_existing: bool,
) -> StoredLabels:
    """Write one delivery's labels inside the verified session directory."""
    if not confirm_front_leg:
        raise SessionStoreError("confirm_front_leg must be true. The anatomical side is not inferred.")
    if front_leg not in {"left", "right"}:
        raise SessionStoreError("front_leg must be left or right.")
    csv_path = labels_path(session.session_dir)
    if csv_path.exists() and not replace_existing:
        raise LabelConflictError("Labels already exist for this session. Pass replace_existing true to replace them.")

    label = PhaseLabel(
        bowler_id=session.manifest.bowler_id,
        delivery_id=session.manifest.delivery_id,
        bfc_frame=bfc_frame,
        ffc_frame=ffc_frame,
        release_frame=release_frame,
        labeler=labeler,
        notes=notes,
    )
    validate_phase_labels(label, session.manifest.decoded_frame_count)

    try:
        updated_manifest = set_manifest_front_leg(session.session_dir / MANIFEST_NAME, front_leg)
    except SessionManifestError as error:
        message = str(error)
        if "already has front_leg" in message:
            raise FrontLegConflictError(message) from error
        raise SessionStoreError(message) from error
    session = VerifiedSession(
        session.session_id,
        session.session_dir,
        session.record,
        updated_manifest,
        session.video_path,
    )

    write_phase_labels(csv_path, (label,))
    try:
        remember_video_filename(
            csv_path,
            session.manifest.bowler_id,
            session.manifest.delivery_id,
            session.record.stored_filename,
        )
    except AnnotationError as error:
        if not replace_existing:
            csv_path.unlink(missing_ok=True)
        raise SessionStoreError(str(error)) from error

    meta = {
        "confirm_front_leg": True,
        "confirm_label_link": bool(confirm_label_link),
        "annotation_provenance": ANNOTATION_PROVENANCE,
        "annotation_byte_identity_verified": False,
    }
    meta_path = session.session_dir / LABELS_META_NAME
    if meta_path.exists():
        write_json_replace(meta_path, meta)
    else:
        write_json_exclusive(meta_path, meta)
    return load_session_labels(session)


def load_session_labels(session: VerifiedSession) -> StoredLabels:
    """Read labels for this session only. Ambiguous files are rejected."""
    csv_path = labels_path(session.session_dir)
    if not csv_path.is_file():
        raise FileNotFoundError("No labels were found.")
    try:
        labels = read_phase_labels(csv_path)
    except (AnnotationError, OSError) as error:
        raise SessionStoreError("Labels are not usable.") from error
    matches = [
        label
        for label in labels
        if label.key == (session.manifest.bowler_id, session.manifest.delivery_id)
    ]
    if len(matches) != 1:
        raise SessionStoreError("Labels are not usable.")
    label = matches[0]
    try:
        recorded = lookup_video_filename(
            csv_path, session.manifest.bowler_id, session.manifest.delivery_id
        )
    except AnnotationError as error:
        raise SessionStoreError("Labels are not usable.") from error
    if recorded != session.record.stored_filename:
        raise SessionStoreError("Labels are not usable.")
    meta = _load_meta(session.session_dir)
    front_leg = session.manifest.front_leg
    if front_leg not in {"left", "right"}:
        raise SessionStoreError("Labels are not usable.")
    return StoredLabels(
        session_id=session.session_id,
        bowler_id=label.bowler_id,
        delivery_id=label.delivery_id,
        video_filename=session.record.stored_filename,
        bfc_frame=label.bfc_frame,
        ffc_frame=label.ffc_frame,
        release_frame=label.release_frame,
        labeler=label.labeler,
        notes=label.notes,
        front_leg=front_leg,
        confirm_front_leg=bool(meta.get("confirm_front_leg")),
        confirm_label_link=bool(meta.get("confirm_label_link")),
        annotation_provenance=ANNOTATION_PROVENANCE,
        annotation_byte_identity_verified=False,
    )


def _load_meta(session_dir: Path) -> dict[str, object]:
    path = session_dir / LABELS_META_NAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
