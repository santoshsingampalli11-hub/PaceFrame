"""Estimator-independent pose data: landmark names, landmarks, and per-frame results.

Nothing in this file depends on MediaPipe. Downstream code (phase detection,
biomechanics) should only use these types.
"""

from dataclasses import dataclass
import math

# 33-point body topology, in the order MediaPipe Pose outputs it. "left" and
# "right" are the athlete's own left and right, not the viewer's. Another
# estimator must map its keypoints onto these names and may provide a subset.
LANDMARK_NAMES: tuple[str, ...] = (
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
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

SKELETON_CONNECTIONS: tuple[tuple[str, str], ...] = (
    ("nose", "left_eye_inner"),
    ("left_eye_inner", "left_eye"),
    ("left_eye", "left_eye_outer"),
    ("left_eye_outer", "left_ear"),
    ("nose", "right_eye_inner"),
    ("right_eye_inner", "right_eye"),
    ("right_eye", "right_eye_outer"),
    ("right_eye_outer", "right_ear"),
    ("mouth_left", "mouth_right"),
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("left_wrist", "left_pinky"),
    ("left_wrist", "left_index"),
    ("left_wrist", "left_thumb"),
    ("left_pinky", "left_index"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("right_wrist", "right_pinky"),
    ("right_wrist", "right_index"),
    ("right_wrist", "right_thumb"),
    ("right_pinky", "right_index"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("left_ankle", "left_heel"),
    ("left_heel", "left_foot_index"),
    ("left_ankle", "left_foot_index"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
    ("right_ankle", "right_heel"),
    ("right_heel", "right_foot_index"),
    ("right_ankle", "right_foot_index"),
)


@dataclass(frozen=True)
class Landmark:
    """One body landmark as estimated in a single image.

    ``x`` and ``y`` are normalized image coordinates: ``x`` is the fraction of
    the image width from the left edge and ``y`` the fraction of the image
    height from the top edge (y grows downward). Values can fall slightly
    outside 0..1 when the model places a landmark outside the frame. They are
    not clamped and are not physical measurements. Non-finite ``x``, ``y``,
    ``visibility``, or ``presence`` values are rejected.

    ``visibility`` and ``presence`` are the model's own scores in 0..1 (likely
    visible / not occluded, and likely inside the image), or ``None`` if the
    estimator does not provide them. They are not measurement accuracy.
    """

    name: str
    x: float
    y: float
    visibility: float | None
    presence: float | None

    def __post_init__(self) -> None:
        if not (math.isfinite(self.x) and math.isfinite(self.y)):
            raise ValueError(
                f"Landmark {self.name!r} coordinates must be finite, got x={self.x!r}, y={self.y!r}."
            )
        for field_name, value in (("visibility", self.visibility), ("presence", self.presence)):
            if value is not None and not math.isfinite(value):
                raise ValueError(
                    f"Landmark {self.name!r} {field_name} must be finite or None, got {value!r}."
                )


@dataclass(frozen=True)
class PoseFrame:
    """Pose estimation result for one video frame.

    ``landmarks`` maps landmark name to ``Landmark`` and is empty when no pose
    was detected.
    """

    frame_index: int
    timestamp_seconds: float
    image_width: int
    image_height: int
    landmarks: dict[str, Landmark]

    @property
    def pose_detected(self) -> bool:
        return bool(self.landmarks)

    def pixel_xy(self, name: str) -> tuple[float, float]:
        """Return a landmark's position in image pixels (origin top-left).

        Use pixels, not normalized coordinates, for any geometry: normalized x
        and y are scaled by different amounts unless the image is square.
        """
        if name not in self.landmarks:
            raise KeyError(f"Landmark {name!r} is not present on frame {self.frame_index}.")
        landmark = self.landmarks[name]
        return landmark.x * self.image_width, landmark.y * self.image_height
