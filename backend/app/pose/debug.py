"""DEBUG visualisation of pose landmarks, for checking tracking by eye.

Usage, from the backend directory:

    python -m app.pose.debug path/to/video.mp4 [--output path.mp4] [--model path.task]

Writes an annotated copy of the video (default: ``debug_output/``) and prints
how many frames had a detected pose. It does not measure anything.
"""

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.pose.estimator import validate_frame_image
from app.pose.landmarks import SKELETON_CONNECTIONS, PoseFrame
from app.pose.mediapipe_estimator import DEFAULT_MODEL_PATH, MediaPipePoseEstimator
from app.video import iter_frames, read_video_metadata

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "debug_output"

# BGR colours. Left and right differ so left/right swaps are easy to spot.
LEFT_COLOR = (0, 165, 255)
RIGHT_COLOR = (255, 255, 0)
CENTER_COLOR = (255, 255, 255)
UNKNOWN_SCORE_COLOR = (255, 255, 255)
LABEL_COLOR = (0, 0, 255)


@dataclass(frozen=True)
class DebugVideoStats:
    """Counts from a debug overlay. Not a measurement of pose accuracy."""

    frame_count: int
    frames_with_pose: int
    longest_run_without_pose: int
    output_path: Path


def draw_pose(image: np.ndarray, pose: PoseFrame) -> np.ndarray:
    """Return a copy of ``image`` with the pose skeleton drawn on it.

    Landmark dots shade continuously from red (visibility 0) to green
    (visibility 1). No landmark is hidden based on its score.
    """
    validate_frame_image(image)
    height, width = image.shape[:2]
    if (width, height) != (pose.image_width, pose.image_height):
        raise ValueError(
            f"Image is {width}x{height} but the pose was estimated on "
            f"{pose.image_width}x{pose.image_height}."
        )

    canvas = image.copy()
    scale = min(width, height)
    line_thickness = max(1, round(scale / 300))
    dot_radius = max(2, round(scale / 150))

    pixels = {name: _pixel(pose, name) for name in pose.landmarks}
    for start, end in SKELETON_CONNECTIONS:
        start_xy = pixels.get(start)
        end_xy = pixels.get(end)
        if start_xy is None or end_xy is None:
            continue
        cv2.line(canvas, start_xy, end_xy, _side_color(start, end), line_thickness, cv2.LINE_AA)
    for name, point in pixels.items():
        if point is None:
            continue
        cv2.circle(
            canvas, point, dot_radius, _score_color(pose.landmarks[name].visibility), -1, cv2.LINE_AA
        )

    label = f"DEBUG pose overlay | frame {pose.frame_index} | {pose.timestamp_seconds:.3f} s"
    if not pose.pose_detected:
        label += " | NO POSE DETECTED"
    font_scale = max(0.4, scale / 900)
    cv2.putText(
        canvas,
        label,
        (10, 10 + round(30 * font_scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        LABEL_COLOR,
        max(1, round(font_scale * 2)),
        cv2.LINE_AA,
    )
    return canvas


def write_debug_video(
    video_path: Path, output_path: Path, model_path: Path = DEFAULT_MODEL_PATH
) -> DebugVideoStats:
    """Write an annotated copy of the video. Does not overwrite the input file."""
    video_path = Path(video_path)
    output_path = Path(output_path)
    if _same_path(video_path, output_path):
        raise ValueError("Debug output path must not be the same as the input video.")

    fps = read_video_metadata(video_path).fps
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = 0
    frames_with_pose = 0
    longest_without = current_without = 0
    writer: cv2.VideoWriter | None = None
    try:
        with MediaPipePoseEstimator(model_path) as estimator:
            for frame in iter_frames(video_path):
                pose = estimator.estimate(frame)
                frame_count += 1
                if pose.pose_detected:
                    frames_with_pose += 1
                    current_without = 0
                else:
                    current_without += 1
                    longest_without = max(longest_without, current_without)
                if writer is None:
                    writer = _open_writer(output_path, fps, pose.image_width, pose.image_height)
                writer.write(draw_pose(frame.image, pose))
    finally:
        if writer is not None:
            writer.release()
    return DebugVideoStats(
        frame_count=frame_count,
        frames_with_pose=frames_with_pose,
        longest_run_without_pose=longest_without,
        output_path=output_path,
    )


def _open_writer(path: Path, fps: float, width: int, height: int) -> cv2.VideoWriter:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV could not create the debug video {path.name}.")
    return writer


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _pixel(pose: PoseFrame, name: str) -> tuple[int, int] | None:
    x, y = pose.pixel_xy(name)
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return round(x), round(y)


def _side_color(start: str, end: str) -> tuple[int, int, int]:
    if start.startswith("left_") and end.startswith("left_"):
        return LEFT_COLOR
    if start.startswith("right_") and end.startswith("right_"):
        return RIGHT_COLOR
    return CENTER_COLOR


def _score_color(score: float | None) -> tuple[int, int, int]:
    if score is None:
        return UNKNOWN_SCORE_COLOR
    score = min(max(score, 0.0), 1.0)
    return 0, round(255 * score), round(255 * (1 - score))


def main() -> None:
    parser = argparse.ArgumentParser(description="DEBUG: draw pose landmarks on a video.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    args = parser.parse_args()

    output = args.output or DEFAULT_OUTPUT_DIR / f"{args.video.stem}_pose_debug.mp4"
    stats = write_debug_video(args.video, output, args.model)

    rate = stats.frames_with_pose / stats.frame_count if stats.frame_count else 0.0
    print(f"Frames processed:          {stats.frame_count}")
    print(f"Frames with a pose:        {stats.frames_with_pose} ({rate:.1%})")
    print(f"Longest run without pose:  {stats.longest_run_without_pose} frames")
    print(f"Debug video written to:    {stats.output_path}")
    print("REAL-WORLD STRESS TEST / DEBUG ONLY — not scientific validation.")


if __name__ == "__main__":
    main()
