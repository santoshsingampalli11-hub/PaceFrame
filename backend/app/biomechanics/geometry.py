"""Plain 2D geometry: distances and vertex angles.

Nothing here depends on MediaPipe, OpenCV, FastAPI, or video files.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class GeometryError(ValueError):
    """A 2D geometry input is undefined or not finite."""


@dataclass(frozen=True)
class Point2D:
    """A point in a 2D plane.

    ``x`` and ``y`` are dimensionless for this module: they must share a unit,
    but the unit is chosen by the caller (pixels, normalised coordinates, etc.).
    """

    x: float
    y: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.x) and math.isfinite(self.y)):
            raise GeometryError(
                f"Point coordinates must be finite, got x={self.x!r}, y={self.y!r}."
            )


def distance(a: Point2D, b: Point2D) -> float:
    """Return the Euclidean distance between ``a`` and ``b``.

    distance = sqrt((a.x - b.x)^2 + (a.y - b.y)^2)
    """
    return math.hypot(a.x - b.x, a.y - b.y)


def angle_abc_degrees(a: Point2D, b: Point2D, c: Point2D) -> float:
    """Return the unsigned interior angle ABC, in degrees, with vertex ``b``.

    Vectors ``BA = A - B`` and ``BC = C - B`` are formed, then

        cos(theta) = (BA · BC) / (|BA| |BC|)
        theta = arccos(clip(cos(theta), -1, 1))

    The result is in ``[0, 180]``. It is not a directed/signed angle, and it is
    not a joint-health or technique score.

    Cosine is clipped into ``[-1, 1]`` before ``acos`` so rounding cannot raise.
    At image-pixel scales this matches an ``atan2(|cross|, dot)`` formulation
    to far below pose-estimation error; the public meaning of the function
    is unchanged.

    Raises ``GeometryError`` if either vector has length zero, because the
    angle is then undefined.
    """
    ba_x = a.x - b.x
    ba_y = a.y - b.y
    bc_x = c.x - b.x
    bc_y = c.y - b.y
    mag_ba = math.hypot(ba_x, ba_y)
    mag_bc = math.hypot(bc_x, bc_y)
    if mag_ba == 0.0 or mag_bc == 0.0:
        raise GeometryError(
            "Angle ABC is undefined because BA or BC has zero length."
        )

    cosine = (ba_x * bc_x + ba_y * bc_y) / (mag_ba * mag_bc)
    cosine = min(1.0, max(-1.0, cosine))
    return math.degrees(math.acos(cosine))
