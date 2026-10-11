"""Read-only inspection of a local video file.

This does not decide whether a recording is suitable for biomechanics.
Encoded FPS is the container rate, not a measured capture clock. The header
frame count is not assumed to equal the number of frames that decode.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2

from app.video.reader import VideoReadError, iter_frames, read_video_metadata

_FPS_LIMIT = (
    "Encoded FPS is the rate stored in the container, not a measured capture clock."
)
_SUITABILITY_LIMIT = (
    "Width, height, and encoded FPS do not show that this video is suitable "
    "for biomechanical analysis."
)
_DURATION_LIMIT = (
    "Estimated duration is the header frame count divided by encoded FPS. "
    "It is not a measured recording length."
)


@dataclass(frozen=True)
class VideoInspection:
    """Metadata and decode checks for one file. The file is not written."""

    filename: str
    width: int | None
    height: int | None
    orientation: str | None
    encoded_fps: float | None
    reported_frame_count: int | None
    decoded_frame_count: int | None
    estimated_duration_seconds: float | None
    first_frame_decoded: bool
    decode_end_status: str
    final_portion_decoded: bool | None
    warnings: tuple[str, ...]
    error: str | None


def inspect_video(path: str | Path) -> VideoInspection:
    """Inspect ``path`` without modifying it.

    A missing file, a file that will not open, or invalid header metadata is
    reported in ``error``. Counts that OpenCV does not provide are left empty
    rather than replaced with a guess.
    """
    video_path = Path(path)
    filename = video_path.name
    if not video_path.exists():
        return _failed(filename, f"Video file not found: {filename}")
    if not video_path.is_file():
        return _failed(filename, f"{filename} is not a file.")

    try:
        metadata = read_video_metadata(video_path)
    except FileNotFoundError as error:
        return _failed(filename, str(error))
    except VideoReadError as error:
        return _failed(filename, str(error))
    except cv2.error as error:
        return _failed(filename, f"OpenCV failed while reading {filename}: {error}")

    decoded = 0
    try:
        for _frame in iter_frames(video_path):
            decoded += 1
    except VideoReadError as error:
        return _from_metadata(
            filename,
            metadata.width,
            metadata.height,
            metadata.fps,
            metadata.frame_count,
            decoded,
            "premature_decode_error",
            (str(error),),
            str(error),
        )
    except cv2.error as error:
        message = f"OpenCV failed while decoding {filename}: {error}"
        return _from_metadata(
            filename,
            metadata.width,
            metadata.height,
            metadata.fps,
            metadata.frame_count,
            decoded,
            "premature_decode_error",
            (message,),
            message,
        )

    warnings = [_FPS_LIMIT, _SUITABILITY_LIMIT, _DURATION_LIMIT]
    if decoded == metadata.frame_count and decoded > 0:
        end_status = "counts_agree"
    else:
        end_status = "header_count_disagreement"
        warnings.append(
            f"Header reports {metadata.frame_count} frames but {decoded} frames were decoded. "
            "The header count and the decoded count disagree. "
            "The reason decoding ended was not determined."
        )
    return _from_metadata(
        filename,
        metadata.width,
        metadata.height,
        metadata.fps,
        metadata.frame_count,
        decoded,
        end_status,
        tuple(warnings),
        None,
    )


def format_inspection(report: VideoInspection) -> str:
    """Return a stable text report. Suitable is not a field in this report."""
    lines = [
        f"filename: {report.filename}",
        f"width: {_value(report.width)}",
        f"height: {_value(report.height)}",
        f"orientation: {_value(report.orientation)}",
        f"encoded_fps: {_value(report.encoded_fps)}",
        f"reported_frame_count: {_value(report.reported_frame_count)}",
        f"decoded_frame_count: {_value(report.decoded_frame_count)}",
        f"estimated_duration_seconds: {_value(report.estimated_duration_seconds)}",
        f"first_frame_decoded: {_yes_no(report.first_frame_decoded)}",
        f"decode_end_status: {report.decode_end_status}",
        f"final_portion_decoded: {_end_flag(report.final_portion_decoded)}",
        "warnings:",
    ]
    if report.warnings:
        lines.extend(f"- {warning}" for warning in report.warnings)
    else:
        lines.append("- none")
    lines.append(f"error: {_value(report.error)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Print an inspection report. Return 0 when the file could be described."""
    parser = argparse.ArgumentParser(
        description="Read local video metadata. This does not judge biomechanical suitability."
    )
    parser.add_argument("video", help="Path to a local video file. The file is not modified.")
    args = parser.parse_args(argv)
    report = inspect_video(args.video)
    print(format_inspection(report))
    return 1 if report.error else 0


def _failed(filename: str, error: str) -> VideoInspection:
    return VideoInspection(
        filename=filename,
        width=None,
        height=None,
        orientation=None,
        encoded_fps=None,
        reported_frame_count=None,
        decoded_frame_count=None,
        estimated_duration_seconds=None,
        first_frame_decoded=False,
        decode_end_status="unavailable",
        final_portion_decoded=None,
        warnings=(error,),
        error=error,
    )


def _from_metadata(
    filename: str,
    width: int,
    height: int,
    fps: float,
    reported_count: int,
    decoded_count: int,
    decode_end_status: str,
    warnings: tuple[str, ...],
    error: str | None,
) -> VideoInspection:
    if decode_end_status == "counts_agree":
        final_portion: bool | None = True
    elif decode_end_status == "premature_decode_error":
        final_portion = False
    else:
        final_portion = None
    return VideoInspection(
        filename=filename,
        width=width,
        height=height,
        orientation=_orientation(width, height),
        encoded_fps=fps,
        reported_frame_count=reported_count,
        decoded_frame_count=decoded_count,
        estimated_duration_seconds=reported_count / fps,
        first_frame_decoded=True,
        decode_end_status=decode_end_status,
        final_portion_decoded=final_portion,
        warnings=warnings,
        error=error,
    )


def _orientation(width: int, height: int) -> str:
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _value(value: object) -> str:
    if value is None:
        return "unavailable"
    return str(value)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _end_flag(value: bool | None) -> str:
    if value is None:
        return "undetermined"
    return "yes" if value else "no"


if __name__ == "__main__":
    raise SystemExit(main())
