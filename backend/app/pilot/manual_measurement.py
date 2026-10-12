"""Measure 2D front-knee angles at manual FFC and Release frames.

The video bytes must match the pilot session manifest before any pose is run.
Manual labels are used only when their filename sidecar matches the manifest
and the caller explicitly confirms that link. A filename is not a SHA-256,
and this command does not certify that the labels were drawn on these bytes.

Knee angles come from ``front_knee_angles_at_manual_phases``. This module
does not change that calculation, detect events, or apply foot corrections.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.annotations.models import AnnotationError, PhaseLabel
from app.annotations.phase_labels import read_phase_labels
from app.annotations.video_identity import lookup_video_filename
from app.biomechanics.front_knee import FrontKneeAngle, front_knee_angles_at_manual_phases
from app.pilot.session_manifest import SessionManifestError, load_session_manifest, verify_session_manifest
from app.pose.estimator import PoseEstimationError, PoseEstimator
from app.pose.landmarks import PoseFrame
from app.video.reader import VideoReadError, iter_frames

REPORT_TYPE = "manual_front_knee_measurement"
SCHEMA_VERSION = 1
_LIMITATIONS = (
    "These are 2D image-plane angles from raw MediaPipe landmarks, not 3D joint angles.",
    "A verified video hash means the file bytes match the manifest. It does not confirm camera view, bowler identity, or measurement accuracy.",
    "The label sidecar stores a filename, not a hash. Human confirmation of that filename is not byte-level proof.",
    "Unconfirmed side-on view and full-body visibility are not scientific approval.",
    "Visibility is not landmark accuracy. A missing pose is reported as unavailable, not as zero degrees.",
    "No manual reference angle and no accuracy statistic is included.",
)


class ManualMeasurementError(ValueError):
    """The manual-phase measurement could not be started."""


@dataclass(frozen=True)
class ManualMeasurementAttempt:
    """A finished attempt. ``output_path`` is set only when a report was written."""

    ok: bool
    message: str
    output_path: Path | None


def measure_manual_front_knee(
    video: str | Path,
    manifest_path: str | Path,
    labels_path: str | Path,
    output: str | Path,
    *,
    confirm_label_link: bool = False,
    estimator: PoseEstimator | None = None,
) -> ManualMeasurementAttempt:
    """Verify the session, then measure FFC and Release on the exact manual frames.

    The video, label CSV, foot-correction files, and manifest are not modified.
    An existing report is not overwritten.
    """
    video_path = Path(video)
    manifest_file = Path(manifest_path)
    labels_file = Path(labels_path)
    output_path = Path(output)
    if output_path.exists():
        return _stopped(f"{output_path.name} already exists. It was not overwritten.")

    try:
        manifest = load_session_manifest(manifest_file)
    except SessionManifestError as error:
        return _stopped(str(error))
    verification = verify_session_manifest(manifest_file, video_path)
    if not verification.ok:
        return _stopped(verification.message)
    if manifest.front_leg not in {"left", "right"}:
        return _stopped(
            "The manifest has no anatomical front leg. Recreate it with --front-leg left or --front-leg right. "
            "The side is not inferred from the picture."
        )

    try:
        label = _one_label(labels_file, manifest.bowler_id, manifest.delivery_id)
        link_message = _label_link(labels_file, manifest.bowler_id, manifest.delivery_id, manifest.video_filename, confirm_label_link)
    except (SessionManifestError, AnnotationError, FileNotFoundError, OSError) as error:
        return _stopped(str(error))
    if link_message is not None:
        return _stopped(link_message)

    poses, pose_error = _collect_poses(video_path, estimator, label)
    if pose_error is not None:
        return _stopped(pose_error)
    ffc, release = front_knee_angles_at_manual_phases(poses, label, manifest.front_leg)
    report = _report(manifest, manifest_file, label, ffc, release)
    try:
        _write_report(output_path, report)
    except ManualMeasurementError as error:
        return _stopped(str(error))
    return ManualMeasurementAttempt(
        True,
        f"Wrote {output_path.name}. Angles are raw 2D measurements, not validated accuracy.",
        output_path,
    )


def main(argv: list[str] | None = None) -> int:
    """Measure manual FFC and Release knee angles for one verified video."""
    parser = argparse.ArgumentParser(
        description="Measure 2D front-knee angles at manual FFC and Release frames. The video is not modified."
    )
    parser.add_argument("--video", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--confirm-label-link",
        action="store_true",
        help="Confirm you checked that the filename sidecar belongs to this video. This is not a byte-level proof.",
    )
    args = parser.parse_args(argv)
    try:
        result = measure_manual_front_knee(
            args.video,
            args.manifest,
            args.labels,
            args.output,
            confirm_label_link=args.confirm_label_link,
        )
    except ManualMeasurementError as error:
        print(str(error))
        return 1
    print(result.message)
    return 0 if result.ok else 1


def _one_label(labels_path: Path, bowler_id: str, delivery_id: str) -> PhaseLabel:
    matches = [label for label in read_phase_labels(labels_path) if label.key == (bowler_id, delivery_id)]
    if len(matches) != 1:
        raise SessionManifestError(
            f"Expected one phase-label row for {bowler_id}/{delivery_id}, found {len(matches)}."
        )
    return matches[0]


def _label_link(
    labels_path: Path,
    bowler_id: str,
    delivery_id: str,
    video_filename: str,
    confirm_label_link: bool,
) -> str | None:
    recorded = lookup_video_filename(labels_path, bowler_id, delivery_id)
    if recorded is None:
        return (
            f"No video-identity record is stored for {bowler_id}/{delivery_id}. "
            "A matching label row does not prove these marks were made on this video."
        )
    if recorded != video_filename:
        return (
            f"The label sidecar names {recorded}, but the manifest video is {video_filename}. "
            "The labels were not used."
        )
    if not confirm_label_link:
        return (
            "The label sidecar matches the filename only. Pass --confirm-label-link after you check that link. "
            "A filename is not a SHA-256, so the labels are not certified as byte-matched."
        )
    return None


def _collect_poses(
    video: Path,
    estimator: PoseEstimator | None,
    label: PhaseLabel,
) -> tuple[tuple[PoseFrame, ...], str | None]:
    if label.ffc_frame is None and label.release_frame is None:
        return (), None
    own_estimator = estimator is None
    if own_estimator:
        from app.pose.mediapipe_estimator import MediaPipePoseEstimator

        estimator = MediaPipePoseEstimator()
    poses: list[PoseFrame] = []
    error: str | None = None
    try:
        for frame in iter_frames(video):
            pose = estimator.estimate(frame)
            if pose.frame_index != frame.index:
                error = (
                    f"Pose frame index {pose.frame_index} does not match decoded frame {frame.index}. "
                    "No neighboring frame was used."
                )
                break
            poses.append(pose)
    except (PoseEstimationError, VideoReadError) as caught:
        error = str(caught)
    finally:
        close = getattr(estimator, "close", None)
        if close is not None:
            close()
    if error is not None:
        return (), error
    return tuple(poses), None


def _report(
    manifest: object,
    manifest_file: Path,
    label: PhaseLabel,
    ffc: FrontKneeAngle,
    release: FrontKneeAngle,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "bowler_id": manifest.bowler_id,
        "delivery_id": manifest.delivery_id,
        "video_filename": manifest.video_filename,
        "video_sha256": manifest.video_sha256,
        "video_byte_identity_verified": True,
        "manifest_filename": manifest_file.name,
        "annotation_provenance": "human_confirmed_filename_sidecar",
        "annotation_byte_identity_verified": False,
        "front_leg": manifest.front_leg,
        "camera_side_on_confirmed": manifest.camera_side_on_confirmed,
        "full_body_visibility_confirmed": manifest.full_body_visibility_confirmed,
        "ffc_frame": label.ffc_frame,
        "release_frame": label.release_frame,
        "ffc": _angle_json(ffc),
        "release": _angle_json(release),
        "warnings": _warnings(manifest),
        "limitations": list(_LIMITATIONS),
    }


def _warnings(manifest: object) -> list[str]:
    warnings = [
        "Label linkage was confirmed by the caller for a matching filename. The sidecar does not store a video hash.",
    ]
    if not manifest.camera_side_on_confirmed:
        warnings.append("Side-on camera view is unconfirmed. That is not scientific approval.")
    if not manifest.full_body_visibility_confirmed:
        warnings.append("Full-body visibility is unconfirmed. That is not scientific approval.")
    return warnings


def _angle_json(result: FrontKneeAngle) -> dict[str, object]:
    return {
        "frame_index": result.frame_index,
        "angle_degrees": result.angle_degrees,
        "status": result.status,
        "reason": result.reason,
        "review_status": result.review_status,
        "source": result.source,
        "warnings": list(result.warnings),
        "evidence": [
            {
                "role": item.role,
                "name": item.name,
                "available": item.available,
                "visibility": item.visibility,
                "presence": item.presence,
                "outside_image": item.outside_image,
                "coordinates_finite": item.coordinates_finite,
            }
            for item in result.evidence
        ],
    }


def _write_report(path: Path, report: dict[str, object]) -> None:
    if path.exists():
        raise ManualMeasurementError(f"{path.name} already exists. It was not overwritten.")
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump(report, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if path.exists():
            raise ManualMeasurementError(f"{path.name} already exists. It was not overwritten.")
        os.replace(temp_path, path)
        temp_path = None
    except OSError as error:
        raise ManualMeasurementError(f"Could not write {path.name}.") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _stopped(message: str) -> ManualMeasurementAttempt:
    return ManualMeasurementAttempt(False, message, None)


if __name__ == "__main__":
    raise SystemExit(main())
