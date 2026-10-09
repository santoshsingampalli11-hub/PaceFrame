"""Map a manually chosen image crop back onto the full frame.

The crop is only a region for the optional pose overlay. It does not identify
the bowler across frames, and it does not move manual event markers.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.pose.landmarks import Landmark, PoseFrame

_MIN_CROP_SIDE = 32


class PoseCropError(ValueError):
    """The selected pose box is not a usable region of the image."""


@dataclass(frozen=True)
class PixelCrop:
    """Inclusive-exclusive pixel box on the original image: ``[x0, x1)``."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0


def pixel_crop(x0: int, y0: int, x1: int, y1: int, image_width: int, image_height: int) -> PixelCrop:
    """Validate a box in original-image pixels."""
    if min(image_width, image_height) <= 0:
        raise PoseCropError("Image size must be positive.")
    for value in (x0, y0, x1, y1):
        if isinstance(value, bool) or not isinstance(value, int):
            raise PoseCropError(f"Crop edges must be integers, got {value!r}.")
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    if left < 0 or top < 0 or right > image_width or bottom > image_height:
        raise PoseCropError("Crop must stay inside the original image.")
    if right - left < _MIN_CROP_SIDE or bottom - top < _MIN_CROP_SIDE:
        raise PoseCropError(f"Crop must be at least {_MIN_CROP_SIDE} pixels on each side.")
    return PixelCrop(left, top, right, bottom)


def crop_point_to_full_frame(
    x_normalized: float,
    y_normalized: float,
    crop: PixelCrop,
    image_width: int,
    image_height: int,
) -> tuple[float, float]:
    """Convert a point inside the crop into full-image normalized coordinates.

    ``x_normalized`` and ``y_normalized`` are fractions of the crop, as
    MediaPipe reports them for the cropped image. The result is a fraction of
    the original frame. Values may fall slightly outside 0..1. They are not
    clamped onto a body.
    """
    x_pixel = crop.x0 + x_normalized * crop.width
    y_pixel = crop.y0 + y_normalized * crop.height
    return x_pixel / image_width, y_pixel / image_height


def remap_pose_to_full_frame(pose: PoseFrame, crop: PixelCrop, image_width: int, image_height: int) -> PoseFrame:
    """Return the same pose with landmark positions in the original image."""
    landmarks: dict[str, Landmark] = {}
    for name, landmark in pose.landmarks.items():
        x_full, y_full = crop_point_to_full_frame(landmark.x, landmark.y, crop, image_width, image_height)
        landmarks[name] = Landmark(
            name=name,
            x=x_full,
            y=y_full,
            visibility=landmark.visibility,
            presence=landmark.presence,
        )
    return PoseFrame(
        frame_index=pose.frame_index,
        timestamp_seconds=pose.timestamp_seconds,
        image_width=image_width,
        image_height=image_height,
        landmarks=landmarks,
    )
