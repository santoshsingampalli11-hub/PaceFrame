"""In-memory manual labels for one delivery.

Event frames change only when the annotator places or clears them. Pose
estimates are not an input.
"""

from __future__ import annotations

from app.annotations.marker_sidecar import MARKER_EVENTS, MarkerPosition
from app.annotations.models import AnnotationError, PhaseLabel


class DeliveryAnnotation:
    """BFC, FFC, and release frames plus optional click positions."""

    def __init__(
        self,
        bowler_id: str,
        delivery_id: str,
        labeler: str = "",
        notes: str = "",
    ) -> None:
        identity = PhaseLabel(bowler_id=bowler_id, delivery_id=delivery_id, labeler=labeler, notes=notes)
        self.bowler_id = identity.bowler_id
        self.delivery_id = identity.delivery_id
        self.labeler = identity.labeler
        self.notes = identity.notes
        self.bfc_frame: int | None = None
        self.ffc_frame: int | None = None
        self.release_frame: int | None = None
        self.markers: dict[str, MarkerPosition] = {}
        self.armed_event: str | None = None
        self.dirty = False

    @property
    def key(self) -> tuple[str, str]:
        return self.bowler_id, self.delivery_id

    def arm(self, event: str) -> None:
        if event not in MARKER_EVENTS:
            raise AnnotationError(f"Unknown marker event {event!r}.")
        self.armed_event = event

    def frame_for(self, event: str) -> int | None:
        return getattr(self, f"{event}_frame")

    def place(self, frame_index: int, x_normalized: float, y_normalized: float) -> None:
        """Record the armed event on this decoded frame at the click.

        The frame index and the click are stored together. Nothing is inferred
        when no event is armed.
        """
        if self.armed_event is None:
            raise AnnotationError("Select BFC, FFC, or Release before clicking.")
        event = self.armed_event
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            raise AnnotationError(f"Frame index must be an integer >= 0, got {frame_index!r}.")
        marker = MarkerPosition(
            bowler_id=self.bowler_id,
            delivery_id=self.delivery_id,
            event=event,
            frame_index=frame_index,
            x_normalized=x_normalized,
            y_normalized=y_normalized,
        )
        frames = {
            "bfc_frame": self.bfc_frame,
            "ffc_frame": self.ffc_frame,
            "release_frame": self.release_frame,
        }
        frames[f"{event}_frame"] = frame_index
        PhaseLabel(
            bowler_id=self.bowler_id,
            delivery_id=self.delivery_id,
            labeler=self.labeler,
            notes=self.notes,
            **frames,
        )
        self.bfc_frame = frames["bfc_frame"]
        self.ffc_frame = frames["ffc_frame"]
        self.release_frame = frames["release_frame"]
        self.markers[event] = marker
        self.dirty = True

    def clear(self, event: str) -> bool:
        """Remove one event frame and its click. Returns whether anything changed."""
        if event not in MARKER_EVENTS:
            raise AnnotationError(f"Unknown marker event {event!r}.")
        if self.frame_for(event) is None and event not in self.markers:
            return False
        setattr(self, f"{event}_frame", None)
        self.markers.pop(event, None)
        self.dirty = True
        return True

    def markers_on_frame(self, frame_index: int) -> dict[str, tuple[float, float]]:
        return {
            event: (marker.x_normalized, marker.y_normalized)
            for event, marker in self.markers.items()
            if marker.frame_index == frame_index
        }

    def to_phase_label(self) -> PhaseLabel:
        return PhaseLabel(
            bowler_id=self.bowler_id,
            delivery_id=self.delivery_id,
            bfc_frame=self.bfc_frame,
            ffc_frame=self.ffc_frame,
            release_frame=self.release_frame,
            labeler=self.labeler,
            notes=self.notes,
        )

    def marker_rows(self) -> tuple[MarkerPosition, ...]:
        return tuple(self.markers[event] for event in MARKER_EVENTS if event in self.markers)
