"""Manual bowling-phase reference labels.

These are annotator-selected frame indices, not laboratory ground truth and
not automatic detections. They are not biomechanical measurements.
"""

from __future__ import annotations

from dataclasses import dataclass

PHASE_LABEL_FIELDNAMES: tuple[str, ...] = (
    "bowler_id",
    "delivery_id",
    "bfc_frame",
    "ffc_frame",
    "release_frame",
    "labeler",
    "notes",
)

_FRAME_FIELDS: tuple[tuple[str, str], ...] = (
    ("bfc_frame", "BFC"),
    ("ffc_frame", "FFC"),
    ("release_frame", "Release"),
)


class AnnotationError(ValueError):
    """A manual phase label is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class PhaseLabel:
    """One delivery's manual BFC / FFC / release frames.

    Frame indices are 0-based decoded-frame indices, matching the video reader.
    Any subset may be omitted (``None``). Present frames must be integers ``>= 0``
    and strictly ordered: BFC < FFC < Release, for whichever pair is present.

    ``labeler`` and ``notes`` may be empty. IDs should be anonymous (for example
    ``B01`` / ``D01``); this type does not enforce a regex.
    """

    bowler_id: str
    delivery_id: str
    bfc_frame: int | None = None
    ffc_frame: int | None = None
    release_frame: int | None = None
    labeler: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "bowler_id", _required_id("bowler_id", self.bowler_id))
        object.__setattr__(self, "delivery_id", _required_id("delivery_id", self.delivery_id))
        object.__setattr__(self, "labeler", _optional_text("labeler", self.labeler))
        object.__setattr__(self, "notes", _optional_text("notes", self.notes))
        object.__setattr__(self, "bfc_frame", _optional_frame("BFC", self.bfc_frame))
        object.__setattr__(self, "ffc_frame", _optional_frame("FFC", self.ffc_frame))
        object.__setattr__(self, "release_frame", _optional_frame("Release", self.release_frame))
        _require_strict_order(self.bfc_frame, self.ffc_frame, self.release_frame)

    @property
    def key(self) -> tuple[str, str]:
        return self.bowler_id, self.delivery_id


def validate_phase_labels(annotation: PhaseLabel, total_frame_count: int) -> None:
    """Check that present frames lie in ``0 .. total_frame_count-1``.

    ``total_frame_count`` is supplied by the caller (for example from video
    metadata). This function does not open a video file.
    """
    if isinstance(total_frame_count, bool) or not isinstance(total_frame_count, int):
        raise AnnotationError(
            f"total_frame_count must be a positive integer, got {total_frame_count!r}."
        )
    if total_frame_count <= 0:
        raise AnnotationError(
            f"total_frame_count must be a positive integer, got {total_frame_count!r}."
        )

    last_legal = total_frame_count - 1
    for field_name, display in _FRAME_FIELDS:
        frame = getattr(annotation, field_name)
        if frame is not None and frame > last_legal:
            raise AnnotationError(
                f"{display} frame {frame} is outside 0..{last_legal} "
                f"(total_frame_count={total_frame_count})."
            )


def _required_id(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise AnnotationError(f"{field_name} must be a string, got {type(value).__name__}.")
    text = value.strip()
    if not text:
        raise AnnotationError(f"{field_name} must not be empty.")
    return text


def _optional_text(field_name: str, value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AnnotationError(f"{field_name} must be a string, got {type(value).__name__}.")
    return value.strip()


def _optional_frame(display: str, value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnnotationError(f"{display} frame must be an integer or None, got {value!r}.")
    if value < 0:
        raise AnnotationError(f"{display} frame must be >= 0, got {value}.")
    return value


def _require_strict_order(bfc: int | None, ffc: int | None, release: int | None) -> None:
    _require_earlier("BFC", bfc, "FFC", ffc)
    _require_earlier("FFC", ffc, "Release", release)
    _require_earlier("BFC", bfc, "Release", release)


def _require_earlier(left_name: str, left: int | None, right_name: str, right: int | None) -> None:
    if left is not None and right is not None and left >= right:
        raise AnnotationError(
            f"{left_name} frame {left} must be earlier than {right_name} frame {right}."
        )
