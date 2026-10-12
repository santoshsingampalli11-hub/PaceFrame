"""Pilot session manifest for one original bowling video.

The manifest records anonymous ids, file metadata, and a SHA-256 of the
video bytes. The hash is the same function used for manual foot corrections.
A matching hash means the bytes are the same. It does not mean the recording
is side-on, that the bowler is fully visible, or that any measurement is accurate.

The phase-label CSV is not used or changed. A filename is not an identity.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.annotations.foot_corrections import file_sha256
from app.video.inspect import inspect_video

SCHEMA_VERSION = 1
SOURCE_TYPE = "original_standardized_recording"
_BOWLER_PREFIX = "B"
_DELIVERY_PREFIX = "D"
_DECODE_END_STATUSES = {
    "counts_agree",
    "header_count_disagreement",
    "premature_decode_error",
    "unavailable",
}


class SessionManifestError(ValueError):
    """A pilot session manifest cannot be created or verified."""


@dataclass(frozen=True)
class PilotSessionManifest:
    """One original recording. Human checks stay false until a person sets them."""

    schema_version: int
    bowler_id: str
    delivery_id: str
    video_filename: str
    video_sha256: str
    video_path: str | None
    width: int
    height: int
    encoded_fps: float
    reported_frame_count: int
    decoded_frame_count: int
    decode_end_status: str
    source_type: str
    camera_side_on_confirmed: bool
    full_body_visibility_confirmed: bool
    front_leg: str | None
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "bowler_id": self.bowler_id,
            "delivery_id": self.delivery_id,
            "video_filename": self.video_filename,
            "video_sha256": self.video_sha256,
            "video_path": self.video_path,
            "width": self.width,
            "height": self.height,
            "encoded_fps": self.encoded_fps,
            "reported_frame_count": self.reported_frame_count,
            "decoded_frame_count": self.decoded_frame_count,
            "decode_end_status": self.decode_end_status,
            "source_type": self.source_type,
            "camera_side_on_confirmed": self.camera_side_on_confirmed,
            "full_body_visibility_confirmed": self.full_body_visibility_confirmed,
            "front_leg": self.front_leg,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ManifestVerification:
    """Result of comparing a manifest with a video file. Files are not written."""

    ok: bool
    message: str


def create_session_manifest(
    video: str | Path,
    bowler_id: str,
    delivery_id: str,
    output: str | Path,
    front_leg: str | None = None,
) -> PilotSessionManifest:
    """Write a new manifest for ``video``. An existing output file is left unchanged."""
    bowler = _anonymous_id("bowler_id", bowler_id, _BOWLER_PREFIX)
    delivery = _anonymous_id("delivery_id", delivery_id, _DELIVERY_PREFIX)
    leg = _optional_leg(front_leg)
    video_path = Path(video)
    output_path = Path(output)
    if output_path.exists():
        raise SessionManifestError(f"{output_path.name} already exists. It was not overwritten.")
    if not video_path.is_file():
        raise SessionManifestError(f"Video file not found: {video_path.name}")

    inspection = inspect_video(video_path)
    if inspection.error or inspection.width is None or inspection.height is None:
        raise SessionManifestError(inspection.error or f"Could not inspect {video_path.name}.")
    if inspection.encoded_fps is None or inspection.reported_frame_count is None or inspection.decoded_frame_count is None:
        raise SessionManifestError(f"Video metadata for {video_path.name} is incomplete.")
    try:
        digest = file_sha256(video_path)
    except OSError as error:
        raise SessionManifestError(f"Could not read {video_path.name}.") from error

    manifest = PilotSessionManifest(
        schema_version=SCHEMA_VERSION,
        bowler_id=bowler,
        delivery_id=delivery,
        video_filename=video_path.name,
        video_sha256=digest,
        video_path=_relative_video_path(video_path, output_path),
        width=inspection.width,
        height=inspection.height,
        encoded_fps=inspection.encoded_fps,
        reported_frame_count=inspection.reported_frame_count,
        decoded_frame_count=inspection.decoded_frame_count,
        decode_end_status=inspection.decode_end_status,
        source_type=SOURCE_TYPE,
        camera_side_on_confirmed=False,
        full_body_visibility_confirmed=False,
        front_leg=leg,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    _write_manifest(output_path, manifest)
    return manifest


def verify_session_manifest(manifest_path: str | Path, video: str | Path) -> ManifestVerification:
    """Re-hash ``video`` and compare it with the manifest. Neither file is modified."""
    path = Path(manifest_path)
    video_path = Path(video)
    try:
        manifest = load_session_manifest(path)
    except SessionManifestError as error:
        return ManifestVerification(False, str(error))
    if not video_path.is_file():
        return ManifestVerification(False, f"Video file not found: {video_path.name}")
    try:
        digest = file_sha256(video_path)
    except OSError as error:
        return ManifestVerification(False, f"Could not read {video_path.name}: {error}")
    if digest != manifest.video_sha256:
        return ManifestVerification(
            False,
            f"Video SHA-256 does not match the manifest for {manifest.bowler_id}/{manifest.delivery_id}. "
            "A matching filename is not video identity.",
        )
    inspection = inspect_video(video_path)
    if inspection.error:
        return ManifestVerification(False, inspection.error)
    mismatches = _metadata_mismatches(manifest, inspection, video_path.name)
    if mismatches:
        return ManifestVerification(False, " ".join(mismatches))
    filename_note = ""
    if video_path.name != manifest.video_filename:
        filename_note = " The filename differs, but the bytes match."
    return ManifestVerification(
        True,
        "Video bytes match the manifest. "
        "This does not confirm camera view, bowler identity, or measurement accuracy."
        + filename_note,
    )


def load_session_manifest(path: str | Path) -> PilotSessionManifest:
    """Read one manifest. An unknown schema version is rejected."""
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise SessionManifestError(f"Manifest file not found: {manifest_path.name}")
    try:
        text = manifest_path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except UnicodeDecodeError as error:
        raise SessionManifestError(f"{manifest_path.name} is not valid UTF-8.") from error
    except json.JSONDecodeError as error:
        raise SessionManifestError(f"{manifest_path.name} is not valid JSON.") from error
    except OSError as error:
        raise SessionManifestError(f"Could not read {manifest_path.name}.") from error
    if not isinstance(payload, dict):
        raise SessionManifestError(f"{manifest_path.name} must contain a JSON object.")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SessionManifestError(f"Unsupported manifest schema version: {version!r}.")
    try:
        return _manifest_from_payload(payload)
    except (KeyError, TypeError, SessionManifestError) as error:
        raise SessionManifestError(f"{manifest_path.name} is not a usable session manifest: {error}") from error


def main(argv: list[str] | None = None) -> int:
    """Create or verify a pilot session manifest."""
    parser = argparse.ArgumentParser(
        description="Record or check the byte identity of one original bowling video."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Write a new manifest. An existing file is not overwritten.")
    create.add_argument("--video", required=True)
    create.add_argument("--bowler", required=True)
    create.add_argument("--delivery", required=True)
    create.add_argument("--output", required=True)
    create.add_argument("--front-leg", choices=("left", "right"), default=None)
    verify = commands.add_parser("verify", help="Re-hash a video and compare it with a manifest.")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--video", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            manifest = create_session_manifest(
                args.video, args.bowler, args.delivery, args.output, args.front_leg
            )
            print(
                f"Wrote {Path(args.output).name} for {manifest.bowler_id}/{manifest.delivery_id}. "
                "Side-on view and full-body visibility are unconfirmed."
            )
            return 0
        result = verify_session_manifest(args.manifest, args.video)
    except SessionManifestError as error:
        print(str(error))
        return 1
    print(result.message)
    return 0 if result.ok else 1


def _write_manifest(path: Path, manifest: PilotSessionManifest) -> None:
    if path.exists():
        raise SessionManifestError(f"{path.name} already exists. It was not overwritten.")
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump(manifest.to_json(), output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if path.exists():
            raise SessionManifestError(f"{path.name} already exists. It was not overwritten.")
        os.replace(temp_path, path)
        temp_path = None
    except OSError as error:
        raise SessionManifestError(f"Could not write {path.name}.") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _manifest_from_payload(payload: dict[str, object]) -> PilotSessionManifest:
    front_leg = payload.get("front_leg")
    video_path = payload.get("video_path")
    encoded_fps = payload.get("encoded_fps")
    if isinstance(encoded_fps, bool) or not isinstance(encoded_fps, (int, float)):
        raise SessionManifestError("encoded_fps must be a finite number greater than 0.")
    if not math.isfinite(float(encoded_fps)) or float(encoded_fps) <= 0:
        raise SessionManifestError("encoded_fps must be a finite number greater than 0.")
    status = _required_text("decode_end_status", payload["decode_end_status"])
    if status not in _DECODE_END_STATUSES:
        raise SessionManifestError(f"decode_end_status is not recognized: {status!r}.")
    created_at = _required_text("created_at", payload["created_at"])
    try:
        datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise SessionManifestError(f"created_at must be a UTC timestamp like 2026-10-12T04:00:00Z, got {created_at!r}.") from error
    return PilotSessionManifest(
        schema_version=SCHEMA_VERSION,
        bowler_id=_anonymous_id("bowler_id", payload["bowler_id"], _BOWLER_PREFIX),
        delivery_id=_anonymous_id("delivery_id", payload["delivery_id"], _DELIVERY_PREFIX),
        video_filename=_filename(payload["video_filename"]),
        video_sha256=_sha256(payload["video_sha256"]),
        video_path=None if video_path is None else _relative_text(video_path),
        width=_positive_int("width", payload["width"]),
        height=_positive_int("height", payload["height"]),
        encoded_fps=float(encoded_fps),
        reported_frame_count=_positive_int("reported_frame_count", payload["reported_frame_count"]),
        decoded_frame_count=_positive_int("decoded_frame_count", payload["decoded_frame_count"]),
        decode_end_status=status,
        source_type=_exact("source_type", payload["source_type"], SOURCE_TYPE),
        camera_side_on_confirmed=_bool_field("camera_side_on_confirmed", payload["camera_side_on_confirmed"]),
        full_body_visibility_confirmed=_bool_field(
            "full_body_visibility_confirmed", payload["full_body_visibility_confirmed"]
        ),
        front_leg=_optional_leg(front_leg),
        created_at=created_at,
    )


def _metadata_mismatches(manifest: PilotSessionManifest, inspection: object, filename: str) -> list[str]:
    mismatches: list[str] = []
    if inspection.width != manifest.width or inspection.height != manifest.height:
        mismatches.append("Frame size does not match the manifest.")
    if inspection.encoded_fps is None or not math.isclose(inspection.encoded_fps, manifest.encoded_fps, rel_tol=0.0, abs_tol=1e-6):
        mismatches.append("Encoded FPS does not match the manifest.")
    if inspection.reported_frame_count != manifest.reported_frame_count:
        mismatches.append("Reported frame count does not match the manifest.")
    if inspection.decoded_frame_count != manifest.decoded_frame_count:
        mismatches.append("Decoded frame count does not match the manifest.")
    if filename == manifest.video_filename and mismatches:
        mismatches.append("The filename matches, but that is not video identity.")
    return mismatches


def _relative_video_path(video: Path, manifest: Path) -> str | None:
    try:
        relative = video.resolve().relative_to(manifest.resolve().parent)
    except (OSError, ValueError):
        return None
    text = relative.as_posix()
    if text.startswith("../") or text == ".." or "/../" in f"/{text}":
        return None
    return text


def _anonymous_id(field_name: str, value: object, prefix: str) -> str:
    if not isinstance(value, str):
        raise SessionManifestError(f"{field_name} must be a string.")
    text = value.strip()
    digits = text[1:]
    if not text.startswith(prefix) or not digits.isascii() or not digits.isdecimal() or len(digits) < 2:
        raise SessionManifestError(
            f"{field_name} must look like {prefix}01, got {value!r}."
        )
    return text


def _optional_leg(value: object) -> str | None:
    if value is None:
        return None
    if value not in {"left", "right"}:
        raise SessionManifestError(f"front_leg must be 'left', 'right', or omitted, got {value!r}.")
    return str(value)


def _filename(value: object) -> str:
    text = _required_text("video_filename", value)
    name = Path(text).name
    if name != text or name in {".", ".."}:
        raise SessionManifestError("video_filename must be a file name, not a path.")
    return name


def _sha256(value: object) -> str:
    text = _required_text("video_sha256", value).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise SessionManifestError("video_sha256 must be a SHA-256 hex digest.")
    return text


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SessionManifestError(f"{field_name} must be a positive integer.")
    return value


def _required_text(field_name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SessionManifestError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _relative_text(value: object) -> str:
    text = _required_text("video_path", value).replace("\\", "/")
    if text.startswith("/") or ".." in Path(text).parts:
        raise SessionManifestError("video_path must be a relative path inside the manifest directory tree.")
    return text


def _exact(field_name: str, value: object, expected: str) -> str:
    if value != expected:
        raise SessionManifestError(f"{field_name} must be {expected!r}.")
    return expected


def _bool_field(field_name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise SessionManifestError(f"{field_name} must be true or false.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
