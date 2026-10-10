"""Compare candidate contact frames with manual reference frames.

Manual labels are annotator-selected references, not perfect ground truth.
An abstention is reported. It is not dropped. ``phase_type`` must be ``BFC``
or ``FFC`` so a misspelled event cannot vanish from both error groups. Time
error uses encoded FPS and is approximate, not a measured capture-clock interval.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceFrameComparison:
    """One BFC or FFC comparison."""

    phase_type: str
    candidate_frame: int | None
    reference_frame: int | None
    outcome: str
    signed_frame_error: int | None
    absolute_frame_error: int | None
    approximate_time_error_seconds: float | None
    note: str


@dataclass(frozen=True)
class ComparisonSummary:
    """Counts across deliveries. Errors stay split by event."""

    evaluated: int
    with_reference: int
    with_candidate: int
    abstentions: int
    bfc_absolute_errors: tuple[int, ...]
    ffc_absolute_errors: tuple[int, ...]


def compare_reference_frame(
    phase_type: str,
    candidate_frame: int | None,
    reference_frame: int | None,
    encoded_fps: float | None = None,
) -> ReferenceFrameComparison:
    """Return signed error as candidate minus reference when both exist."""
    if phase_type not in {"BFC", "FFC"}:
        raise ValueError(f"phase_type must be 'BFC' or 'FFC', got {phase_type!r}.")
    _require_frame("candidate_frame", candidate_frame)
    _require_frame("reference_frame", reference_frame)
    _require_fps(encoded_fps)
    if candidate_frame is None and reference_frame is None:
        return ReferenceFrameComparison(
            phase_type,
            None,
            None,
            "abstained",
            None,
            None,
            None,
            "Both the candidate and the manual reference are missing.",
        )
    if candidate_frame is None:
        return ReferenceFrameComparison(
            phase_type,
            None,
            reference_frame,
            "abstained",
            None,
            None,
            None,
            "No candidate frame. The comparison is an abstention, not a zero error.",
        )
    if reference_frame is None:
        return ReferenceFrameComparison(
            phase_type,
            candidate_frame,
            None,
            "reference_missing",
            None,
            None,
            None,
            "No manual reference frame. Comparison is unavailable.",
        )
    signed = candidate_frame - reference_frame
    time_error = None
    note = "Frame error only. Manual reference is not laboratory ground truth."
    if encoded_fps is not None and encoded_fps > 0:
        time_error = signed / encoded_fps
        note = (
            "approximate_time_error_seconds uses encoded FPS, not a measured capture clock. "
            + note
        )
    return ReferenceFrameComparison(
        phase_type,
        candidate_frame,
        reference_frame,
        "compared",
        signed,
        abs(signed),
        time_error,
        note,
    )


def summarise_comparisons(rows: Sequence[ReferenceFrameComparison]) -> ComparisonSummary:
    """Count abstentions instead of ignoring them."""
    bfc: list[int] = []
    ffc: list[int] = []
    for row in rows:
        if row.outcome == "compared" and row.absolute_frame_error is not None:
            if row.phase_type == "BFC":
                bfc.append(row.absolute_frame_error)
            elif row.phase_type == "FFC":
                ffc.append(row.absolute_frame_error)
    return ComparisonSummary(
        evaluated=len(rows),
        with_reference=sum(row.reference_frame is not None for row in rows),
        with_candidate=sum(row.candidate_frame is not None for row in rows),
        abstentions=sum(row.outcome == "abstained" for row in rows),
        bfc_absolute_errors=tuple(bfc),
        ffc_absolute_errors=tuple(ffc),
    )


def _require_frame(name: str, value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be an integer >= 0 or None, got {value!r}.")


def _require_fps(value: float | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"encoded_fps must be a finite number > 0 or None, got {value!r}.")
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        raise ValueError(f"encoded_fps must be finite and > 0, got {value!r}.")
