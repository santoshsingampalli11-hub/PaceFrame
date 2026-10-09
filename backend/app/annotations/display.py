"""Map window clicks onto a real video frame and draw manual markers.

The source image is letterboxed so its aspect ratio is preserved. Marker
positions are chosen by the annotator. They are not ankle, wrist, or ball
measurements.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.annotations.foot_corrections import FOOT_LABELS
from app.pose.landmarks import PoseFrame

EVENT_LABELS: dict[str, str] = {
    "bfc": "BFC",
    "ffc": "FFC",
    "release": "RELEASE",
}

# BGR. These mark a manual click, not a pose landmark.
EVENT_COLORS: dict[str, tuple[int, int, int]] = {
    "bfc": (0, 215, 255),
    "ffc": (0, 180, 0),
    "release": (255, 0, 255),
}

OVERLAY_LANDMARKS: tuple[str, ...] = (
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
)

# BGR fill colors for the optional pose dots. The outline is white, except
# the white preset, which uses a black outline so the ring stays visible.
# Changing color does not move a landmark or make it more accurate.
POSE_COLOR_PRESETS: tuple[str, ...] = ("black", "dark_red", "white", "yellow", "cyan")
POSE_FILL_BGR: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "dark_red": (0, 0, 139),
    "white": (255, 255, 255),
    "yellow": (0, 255, 255),
    "cyan": (255, 255, 0),
}


def next_pose_color(current: str) -> str:
    """Return the next pose-dot preset. Unknown names restart at black."""
    if current not in POSE_COLOR_PRESETS:
        return POSE_COLOR_PRESETS[0]
    index = POSE_COLOR_PRESETS.index(current)
    return POSE_COLOR_PRESETS[(index + 1) % len(POSE_COLOR_PRESETS)]


def pose_outline_bgr(preset: str) -> tuple[int, int, int]:
    if preset == "white":
        return (0, 0, 0)
    return (255, 255, 255)


@dataclass(frozen=True)
class Letterbox:
    """Where the original frame sits inside the display canvas."""

    image_width: int
    image_height: int
    canvas_width: int
    canvas_height: int
    content_width: int
    content_height: int
    pad_x: int
    pad_y: int


def letterbox_for(image_width: int, image_height: int, canvas_width: int, canvas_height: int) -> Letterbox:
    """Fit ``image`` inside the canvas without stretching it."""
    if min(image_width, image_height, canvas_width, canvas_height) <= 0:
        raise ValueError("Image and canvas sizes must be positive.")
    scale = min(canvas_width / image_width, canvas_height / image_height)
    content_width = max(1, min(canvas_width, int(round(image_width * scale))))
    content_height = max(1, min(canvas_height, int(round(image_height * scale))))
    pad_x = (canvas_width - content_width) // 2
    pad_y = (canvas_height - content_height) // 2
    return Letterbox(
        image_width=image_width,
        image_height=image_height,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        content_width=content_width,
        content_height=content_height,
        pad_x=pad_x,
        pad_y=pad_y,
    )


def canvas_point_to_normalized(
    point_x: float,
    point_y: float,
    box: Letterbox,
) -> tuple[float, float] | None:
    """Map a point on the letterboxed canvas to normalized image coordinates.

    Returns ``None`` when the point is in the padding around the frame.
    Normalized ``x`` is a fraction of image width and ``y`` a fraction of
    image height. Both stay inside 0..1 for a click on the frame.
    """
    local_x = point_x - box.pad_x
    local_y = point_y - box.pad_y
    if local_x < 0 or local_y < 0 or local_x >= box.content_width or local_y >= box.content_height:
        return None
    x_norm = (local_x / box.content_width)
    y_norm = (local_y / box.content_height)
    return x_norm, y_norm


def normalized_to_canvas_point(
    x_normalized: float,
    y_normalized: float,
    box: Letterbox,
) -> tuple[float, float]:
    """Inverse of ``canvas_point_to_normalized`` for a point inside the frame."""
    return (
        box.pad_x + x_normalized * box.content_width,
        box.pad_y + y_normalized * box.content_height,
    )


def map_click_to_normalized(
    click_x: float,
    click_y: float,
    window_width: int,
    window_height: int,
    canvas_width: int,
    canvas_height: int,
    image_width: int,
    image_height: int,
) -> tuple[float, float] | None:
    """Map a GUI click to normalized coordinates on the original frame.

    ``click_x`` and ``click_y`` must already be in the image passed to
    ``imshow``. OpenCV scales window clicks into that image before the mouse
    callback. Scaling them again by the window rectangle shifts the marker.
    Padding around the letterboxed frame does not produce a marker, and
    out-of-range clicks are ignored rather than clamped.
    """
    if click_x < 0 or click_y < 0 or click_x >= canvas_width or click_y >= canvas_height:
        return None
    if abs(window_width - canvas_width) > 2 or abs(window_height - canvas_height) > 2:
        return None
    box = letterbox_for(image_width, image_height, canvas_width, canvas_height)
    return canvas_point_to_normalized(click_x, click_y, box)


def map_window_click_to_normalized(
    click_x: float,
    click_y: float,
    window_width: int,
    window_height: int,
    image_width: int,
    image_height: int,
) -> tuple[float, float] | None:
    """Map a window click onto the original frame.

    The frame is letterboxed into a canvas of the window's size, so one scale
    step is enough when the shown image matches the window.
    """
    box = letterbox_for(image_width, image_height, window_width, window_height)
    return canvas_point_to_normalized(click_x, click_y, box)


def draw_manual_markers(
    image: np.ndarray,
    markers: dict[str, tuple[float, float]],
) -> np.ndarray:
    """Draw click markers on a copy of a real frame.

    ``markers`` maps an event name to normalized ``(x, y)`` on this image.
    """
    canvas = image.copy()
    height, width = canvas.shape[:2]
    radius = max(4, min(width, height) // 80)
    for event, (x_norm, y_norm) in markers.items():
        if event not in EVENT_COLORS:
            continue
        center = (int(round(x_norm * width)), int(round(y_norm * height)))
        if not (0 <= center[0] < width and 0 <= center[1] < height):
            continue
        color = EVENT_COLORS[event]
        cv2.circle(canvas, center, radius, color, 2, cv2.LINE_AA)
        cv2.circle(canvas, center, 2, color, -1, cv2.LINE_AA)
        cv2.putText(
            canvas,
            EVENT_LABELS[event],
            (center[0] + radius + 2, center[1]),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )
    return canvas


def draw_landmark_subset(
    image: np.ndarray,
    pose: PoseFrame | None,
    pose_color: str = "black",
) -> np.ndarray:
    """Draw pose dots on a copy of the original frame.

    Each dot is a filled circle in the selected color with a thin contrasting
    outline. Positions come from the pose unchanged. These dots are not
    contact or release events, and the color is not a measure of accuracy.
    """
    canvas = image.copy()
    if pose is None or not pose.pose_detected:
        return canvas
    height, width = canvas.shape[:2]
    radius = max(3, min(width, height) // 120)
    fill = POSE_FILL_BGR.get(pose_color, POSE_FILL_BGR["black"])
    outline = pose_outline_bgr(pose_color if pose_color in POSE_FILL_BGR else "black")
    for name in OVERLAY_LANDMARKS:
        if name not in pose.landmarks:
            continue
        x_pixel, y_pixel = pose.pixel_xy(name)
        if not (np.isfinite(x_pixel) and np.isfinite(y_pixel)):
            continue
        center = (int(round(x_pixel)), int(round(y_pixel)))
        if 0 <= center[0] < width and 0 <= center[1] < height:
            cv2.circle(canvas, center, radius, outline, -1, cv2.LINE_AA)
            inner = max(1, radius - 1)
            cv2.circle(canvas, center, inner, fill, -1, cv2.LINE_AA)
    return canvas


def draw_foot_corrections(image: np.ndarray, corrections: dict[str, tuple[float, float]]) -> np.ndarray:
    """Draw human foot corrections. These are not raw pose dots or event marks."""
    canvas = image.copy()
    height, width = canvas.shape[:2]
    color = (255, 255, 255)
    for name, (x_norm, y_norm) in corrections.items():
        if name not in FOOT_LABELS:
            continue
        center = (int(round(x_norm * width)), int(round(y_norm * height)))
        if not (0 <= center[0] < width and 0 <= center[1] < height):
            continue
        cv2.drawMarker(canvas, center, color, cv2.MARKER_CROSS, 14, 1, cv2.LINE_AA)
        cv2.putText(
            canvas,
            FOOT_LABELS[name],
            (center[0] + 8, center[1] - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            color,
            1,
            cv2.LINE_AA,
        )
    return canvas


def render_frame(
    image: np.ndarray,
    canvas_width: int,
    canvas_height: int,
    markers: dict[str, tuple[float, float]],
    pose: PoseFrame | None,
    hud_lines: list[str],
    foot_corrections: dict[str, tuple[float, float]] | None = None,
    show_raw_pose: bool = True,
    pose_color: str = "black",
) -> np.ndarray:
    """Letterbox a real frame into a canvas.

    Raw pose dots, manual foot corrections, and event markers are drawn as
    separate layers. A correction is not blended into the raw pose.
    """
    annotated = image
    if show_raw_pose:
        annotated = draw_landmark_subset(annotated, pose, pose_color)
    else:
        annotated = image.copy()
    annotated = draw_foot_corrections(annotated, {} if foot_corrections is None else foot_corrections)
    annotated = draw_manual_markers(annotated, markers)
    box = letterbox_for(image.shape[1], image.shape[0], canvas_width, canvas_height)
    canvas = np.zeros((canvas_height, canvas_width, 3), np.uint8)
    resized = cv2.resize(
        annotated,
        (box.content_width, box.content_height),
        interpolation=cv2.INTER_AREA,
    )
    canvas[box.pad_y : box.pad_y + box.content_height, box.pad_x : box.pad_x + box.content_width] = resized
    y = 22
    for line in hud_lines:
        cv2.putText(canvas, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        y += 18
    return canvas
