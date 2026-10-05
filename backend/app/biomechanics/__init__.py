"""2D geometry for later biomechanics. Independent of video, pose, and FastAPI.

Coordinates are abstract numbers in any consistent unit (for example image
pixels). Distances use those same units. Angles are unsigned interior angles
in degrees in the closed range 0..180.

This module does not interpret cricket technique, bowling phases, or injury.
"""

from app.biomechanics.geometry import (
    GeometryError,
    Point2D,
    angle_abc_degrees,
    distance,
)

__all__ = [
    "GeometryError",
    "Point2D",
    "angle_abc_degrees",
    "distance",
]
