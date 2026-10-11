"""Read-only pilot review of one video's pose diagnostics.

The command inspects the file, runs the existing pose estimator, and
summarises the existing quality and temporal diagnostics. It does not grade
the recording, identify the bowler, or change landmark coordinates.

Full-resolution frames are not kept. The file may be read more than once.
A long video can take several minutes. Frames are not dropped.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2

from app.annotations.display import draw_landmark_subset
from app.pose.estimator import PoseEstimationError, PoseEstimator, estimate_video_poses
from app.pose.landmarks import PoseFrame
from app.quality.diagnostics import diagnose_pose_frames
from app.quality.temporal import continuity_notes, landmark_deviations, landmark_steps, largest_steps
from app.video.inspect import VideoInspection, inspect_video
from app.video.reader import VideoReadError, iter_frames

_TIME_NOTE = (
    "This command reads the file more than once and keeps pose results, not full frames. "
    "A long video may take several minutes. No frames are dropped."
)
_CAVEATS = (
    "Successful decoding is not biomechanical suitability.",
    "A detected pose is not proof that the person is the bowler.",
    "Visibility and presence are model scores, not proof that a landmark is correctly placed.",
    "Foot landmarks can sit off the shoe or on the ground.",
    "A side-on camera angle has to be confirmed by a person.",
    "Whether the whole body stays in frame has to be confirmed by a person.",
    "Motion blur can make localization less reliable. This report does not measure blur.",
    "Encoded FPS is the container rate, not a verified camera clock.",
    "The overlay draws the raw pose. It does not move points onto the body or apply foot corrections.",
)


class PilotReviewError(ValueError):
    """The pilot review could not be started."""


@dataclass(frozen=True)
class PilotReviewResult:
    """Where the report was written, and any error that stopped pose processing."""

    report_path: Path | None
    image_paths: tuple[Path, ...]
    error: str | None


def run_pilot_review(
    video: str | Path,
    output: str | Path,
    review_frames: Sequence[int] = (),
    estimator: PoseEstimator | None = None,
) -> PilotReviewResult:
    """Inspect ``video``, summarise pose diagnostics, and optionally save raw overlays.

    ``estimator`` is for tests. When it is omitted, the MediaPipe video-mode
    estimator is used and closed before this function returns. The source
    video is not modified. Manual foot corrections are not read.
    """
    video_path = Path(video)
    output_path = Path(output)
    _prepare_output(output_path)
    inspection = inspect_video(video_path)
    if inspection.error:
        report = _write_report(output_path, _failure_text(inspection))
        return PilotReviewResult(report, (), inspection.error)

    own_estimator = estimator is None
    if own_estimator:
        from app.pose.mediapipe_estimator import MediaPipePoseEstimator

        estimator = MediaPipePoseEstimator()
    poses: list[PoseFrame] = []
    error: str | None = None
    try:
        for pose in estimate_video_poses(video_path, estimator):
            poses.append(pose)
    except (PoseEstimationError, VideoReadError, cv2.error) as caught:
        error = str(caught)
    finally:
        close = getattr(estimator, "close", None)
        if close is not None:
            close()

    if error or not poses:
        text = _failure_text(inspection)
        if error:
            text += f"\npose_error: {error}\n"
        report = _write_report(output_path, text)
        return PilotReviewResult(report, (), error or "No pose frames were produced.")

    selected, selection_warnings = _select_review_frames(review_frames, len(poses))
    images: tuple[Path, ...] = ()
    export_error: str | None = None
    if selected:
        images, export_error = _export_frames(video_path, poses, selected, output_path)
    text = _success_text(inspection, poses, selection_warnings, images)
    if export_error:
        text += (
            f"export_error: {export_error}\n"
            "Analysis of decoded frames was summarised. Frame export did not finish.\n"
        )
    report = _write_report(output_path, text)
    return PilotReviewResult(report, images, export_error)


def main(argv: list[str] | None = None) -> int:
    """Print the report path. Return 1 when inspection or pose processing fails."""
    parser = argparse.ArgumentParser(
        description="Summarise pose diagnostics for one local video. The video is not modified."
    )
    parser.add_argument("--video", required=True, help="Path to a local video file.")
    parser.add_argument("--output", required=True, help="Directory for the report and any frame images.")
    parser.add_argument(
        "--frame",
        action="append",
        type=int,
        default=[],
        help="Zero-based frame index to export with the raw pose overlay. Repeat for more than one frame.",
    )
    args = parser.parse_args(argv)
    try:
        result = run_pilot_review(args.video, args.output, args.frame)
    except PilotReviewError as error:
        print(str(error))
        return 1
    if result.report_path is not None:
        print(result.report_path)
    if result.error:
        print(result.error)
        return 1
    return 0


def _prepare_output(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise PilotReviewError(f"{path.name} is not a directory.")
    path.mkdir(parents=True, exist_ok=True)


def _select_review_frames(requested: Sequence[int], decoded_count: int) -> tuple[tuple[int, ...], tuple[str, ...]]:
    chosen: list[int] = []
    warnings: list[str] = []
    seen: set[int] = set()
    last = decoded_count - 1
    for index in requested:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            warnings.append(f"Review frame {index!r} is not a valid index. No image was exported.")
            continue
        if index in seen:
            warnings.append(
                f"Review frame {index} was requested more than once. One image was exported."
            )
            continue
        if index > last:
            warnings.append(
                f"Review frame {index} is outside decoded frames 0..{last}. No image was exported."
            )
            continue
        if index not in seen:
            chosen.append(index)
            seen.add(index)
    return tuple(chosen), tuple(warnings)


def _export_frames(
    video: Path,
    poses: Sequence[PoseFrame],
    indexes: Sequence[int],
    output: Path,
) -> tuple[tuple[Path, ...], str | None]:
    by_index = {pose.frame_index: pose for pose in poses}
    wanted = set(indexes)
    written: list[Path] = []
    for frame in iter_frames(video):
        if frame.index not in wanted:
            continue
        pose = by_index.get(frame.index)
        image = draw_landmark_subset(frame.image, pose)
        destination = output / f"frame_{frame.index}.png"
        try:
            written_ok = cv2.imwrite(str(destination), image)
        except cv2.error as error:
            return tuple(written), f"Could not write {destination.name}: {error}"
        if not written_ok:
            return tuple(written), f"Could not write {destination.name}."
        written.append(destination)
        if len(written) == len(wanted):
            break
    return tuple(written), None


def _success_text(
    inspection: VideoInspection,
    poses: Sequence[PoseFrame],
    selection_warnings: Sequence[str],
    images: Sequence[Path],
) -> str:
    quality = diagnose_pose_frames(poses)
    notes = continuity_notes(poses)
    steps = largest_steps(landmark_steps(poses))
    deviations = landmark_deviations(poses)
    missing_pose = quality.frame_count - quality.frames_with_pose
    lines = [
        _TIME_NOTE,
        "",
        f"filename: {inspection.filename}",
        f"width: {inspection.width}",
        f"height: {inspection.height}",
        f"orientation: {inspection.orientation}",
        f"encoded_fps: {inspection.encoded_fps}",
        f"reported_frame_count: {inspection.reported_frame_count}",
        f"decoded_frame_count: {inspection.decoded_frame_count}",
        f"estimated_duration_seconds: {inspection.estimated_duration_seconds}",
        "duration_unit: header frame count / encoded FPS, not a measured clock",
        f"pose_frames: {quality.frames_with_pose}",
        f"pose_frame_count: {quality.frame_count}",
        f"pose_detection_percent: {quality.pose_coverage * 100.0:.2f}",
        "pose_detection_meaning: percent of decoded frames with a non-empty pose. Not bowler identity and not accuracy.",
        f"missing_pose_count: {missing_pose}",
        f"longest_missing_pose_run_frames: {quality.longest_run_without_pose}",
        f"missing_pose_run_count: {quality.missing_pose_run_count}",
        "",
        "landmark_availability:",
        "unit: frames_with_landmark is a count. mean_visibility and mean_presence are model scores from 0 to 1 when the model supplied them. They are not accuracy.",
    ]
    for signal in quality.landmark_signals:
        lines.append(
            f"- {signal.name}: frames_with_landmark={signal.frames_with_landmark}, "
            f"mean_visibility={_optional(signal.mean_visibility)}, "
            f"mean_presence={_optional(signal.mean_presence)}"
        )
    lines.extend(["", "largest_normalized_landmark_steps:", "unit: hypot(dx, dy) in normalized image coordinates, not metres or pixels."])
    if steps:
        for step in steps:
            lines.append(
                f"- {step.name}: {step.from_frame}->{step.to_frame} {step.normalized_displacement:.4f}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "three_frame_deviation:", "unit: normalized image distance from the middle point to the midpoint of its neighbors. Not a jitter grade."])
    if deviations:
        largest = max(deviations, key=lambda item: item.normalized_deviation)
        lines.append(f"count: {len(deviations)}")
        lines.append(
            f"largest: {largest.name} frame {largest.frame_index} {largest.normalized_deviation:.4f}"
        )
    else:
        lines.append("count: 0")
        lines.append("largest: none")
    lines.extend(["", notes.note, "", "review_frames:"])
    if images:
        lines.extend(f"- {path.name}" for path in images)
    else:
        lines.append("- none")
    lines.extend(["", "warnings:"])
    warnings = list(inspection.warnings) + list(selection_warnings)
    lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(["", "caveats:"])
    lines.extend(f"- {caveat}" for caveat in _CAVEATS)
    return "\n".join(lines) + "\n"


def _failure_text(inspection: VideoInspection) -> str:
    lines = [
        _TIME_NOTE,
        "",
        f"filename: {inspection.filename}",
        f"width: {_optional(inspection.width)}",
        f"height: {_optional(inspection.height)}",
        f"orientation: {_optional(inspection.orientation)}",
        f"encoded_fps: {_optional(inspection.encoded_fps)}",
        f"reported_frame_count: {_optional(inspection.reported_frame_count)}",
        f"decoded_frame_count: {_optional(inspection.decoded_frame_count)}",
        f"estimated_duration_seconds: {_optional(inspection.estimated_duration_seconds)}",
        f"error: {inspection.error}",
        "",
        "warnings:",
    ]
    lines.extend(f"- {warning}" for warning in inspection.warnings)
    lines.extend(["", "caveats:"])
    lines.extend(f"- {caveat}" for caveat in _CAVEATS)
    return "\n".join(lines) + "\n"


def _write_report(output: Path, text: str) -> Path:
    destination = output / "report.txt"
    destination.write_text(text, encoding="utf-8")
    return destination


def _optional(value: object) -> str:
    if value is None:
        return "unavailable"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
