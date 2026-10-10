"""Experimental image-space candidates for back-foot and front-foot contact.

A 2D pose does not measure ground contact. This module reports frames where a
named anatomical foot is briefly still in the image, and only when the caller
supplies which anatomical side is the back foot and which is the front foot.
Left and right are the athlete's sides, not the sides of the picture.

A near-zero step can also come from a foot that is waiting before the run-up,
a foot that has finished, a hovering foot, a wrong point stuck on the grass,
another person, a repeated video frame, or the camera moving with the athlete.
None of those is confirmed back-foot or front-foot contact.

``stable_displacement`` is a provisional normalized-image limit. It is not a
validated contact threshold. The default is ``None``, which abstains instead
of naming a contact frame. Negative values, NaN, infinity, and booleans are
rejected. Frame indices must strictly increase. A reversed or duplicate
sequence is an input error, not an abstention. A boolean is not a visual-break
frame.

Release detection is not implemented. Candidates are an experimental
image-space heuristic. They are not a calibrated probability, a force, or an
injury assessment.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.biomechanics.geometry import Point2D, distance
from app.pose.landmarks import PoseFrame

_FOOT_PARTS = ("ankle", "heel", "foot_index")
_NOT_CONTACT = (
    "Image-space stabilization is not ground contact, not a force, "
    "and not a validated detection."
)


@dataclass(frozen=True)
class ContactHeuristicConfig:
    """Caller-supplied provisional settings.

    ``stable_displacement`` is a maximum ``hypot(dx, dy)`` in normalized image
    coordinates. ``None`` means contact frames are not inferred.
    """

    stable_displacement: float | None = None

    def __post_init__(self) -> None:
        value = self.stable_displacement
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContactInputError(
                f"stable_displacement must be a finite number >= 0 or None, got {value!r}."
            )
        if value != value or value in (float("inf"), float("-inf")) or value < 0:
            raise ContactInputError(
                f"stable_displacement must be finite and >= 0, got {value!r}."
            )


class ContactInputError(ValueError):
    """A contact-search input cannot be interpreted."""


@dataclass(frozen=True)
class FootSettlement:
    """One anatomical side looked still in the image on one frame."""

    side: str
    frame_index: int
    landmark_names: tuple[str, ...]
    max_adjacent_displacement: float


@dataclass(frozen=True)
class ContactCandidate:
    """A possible BFC or FFC frame. ``provisional_score`` is not a probability."""

    phase_type: str
    frame_index: int
    evidence: str
    landmark_names: tuple[str, ...]
    provisional_score: float | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ContactSearchResult:
    """Candidate evidence, or an explicit abstention. Never an invented frame."""

    status: str
    explanation: str
    settlements: tuple[FootSettlement, ...]
    bfc_candidates: tuple[ContactCandidate, ...]
    ffc_candidates: tuple[ContactCandidate, ...]
    ordered_pair: tuple[ContactCandidate, ContactCandidate] | None


def search_contact_candidates(
    frames: Sequence[PoseFrame],
    config: ContactHeuristicConfig | None = None,
    *,
    back_foot: str | None = None,
    front_foot: str | None = None,
    visual_break_after: Sequence[int] = (),
) -> ContactSearchResult:
    """Look for still foot segments. Abstain when the evidence is not usable."""
    settings = config or ContactHeuristicConfig()
    _require_increasing(frames)
    _require_breaks(visual_break_after)
    if len(frames) < 3:
        return _result("insufficient", "Fewer than three frames. No contact frame was inferred.")
    if settings.stable_displacement is None:
        return _result(
            "abstain",
            "No provisional stabilization limit was supplied. No contact frame was inferred.",
        )
    if back_foot not in {"left", "right"} or front_foot not in {"left", "right"} or back_foot == front_foot:
        settlements = _settlements(frames, settings.stable_displacement)
        return _result(
            "abstain",
            "Back foot and front foot were not given as two different anatomical sides "
            "(athlete left or right). Settled frames are not labeled BFC or FFC.",
            settlements=settlements,
        )

    settlements = _settlements(frames, settings.stable_displacement)
    warnings = (_NOT_CONTACT,)
    bfc = _candidates("BFC", back_foot, settlements, warnings)
    ffc = _candidates("FFC", front_foot, settlements, warnings)
    if not bfc and not ffc:
        return _result(
            "abstain",
            "No foot stayed within the provisional image-space limit. No contact frame was inferred.",
            settlements=settlements,
        )
    pair = _ordered_pair(bfc, ffc, visual_break_after)
    multiple = len(bfc) > 1 or len(ffc) > 1
    if pair is not None:
        status = "candidates"
        explanation = (
            "One BFC candidate precedes one FFC candidate. "
            "This is a provisional image-space result, not confirmed contact."
        )
    elif multiple or (bfc and ffc):
        status = "ambiguous"
        explanation = "Candidate frames are ambiguous or out of order. No event times were invented."
    else:
        status = "candidates"
        explanation = "Only one of BFC or FFC has a candidate frame. The missing event was not filled in."
    return _result(status, explanation, settlements, bfc, ffc, pair)


def _settlements(frames: Sequence[PoseFrame], limit: float) -> tuple[FootSettlement, ...]:
    found: list[FootSettlement] = []
    for side in ("left", "right"):
        for index in range(1, len(frames) - 1):
            names, largest = _settled_parts(frames, index, side, limit)
            if not names:
                continue
            found.append(
                FootSettlement(
                    side=side,
                    frame_index=frames[index].frame_index,
                    landmark_names=names,
                    max_adjacent_displacement=largest,
                )
            )
    return tuple(found)


def _settled_parts(
    frames: Sequence[PoseFrame],
    index: int,
    side: str,
    limit: float,
) -> tuple[tuple[str, ...], float]:
    previous, middle, following = frames[index - 1], frames[index], frames[index + 1]
    if middle.frame_index - previous.frame_index != 1 or following.frame_index - middle.frame_index != 1:
        return (), 0.0
    if not (previous.pose_detected and middle.pose_detected and following.pose_detected):
        return (), 0.0
    names: list[str] = []
    largest = 0.0
    for part in _FOOT_PARTS:
        name = f"{side}_{part}"
        inbound = _step(previous, middle, name)
        outbound = _step(middle, following, name)
        if inbound is None or outbound is None:
            continue
        if inbound <= limit and outbound <= limit:
            names.append(name)
            largest = max(largest, inbound, outbound)
    return tuple(names), largest


def _step(earlier: PoseFrame, later: PoseFrame, name: str) -> float | None:
    if name not in earlier.landmarks or name not in later.landmarks:
        return None
    start = earlier.landmarks[name]
    end = later.landmarks[name]
    return distance(Point2D(start.x, start.y), Point2D(end.x, end.y))


def _candidates(
    phase_type: str,
    side: str,
    settlements: Sequence[FootSettlement],
    warnings: tuple[str, ...],
) -> tuple[ContactCandidate, ...]:
    return tuple(
        ContactCandidate(
            phase_type=phase_type,
            frame_index=item.frame_index,
            evidence=(
                f"Athlete {side} foot landmarks {', '.join(item.landmark_names)} "
                f"moved at most {item.max_adjacent_displacement:.4f} normalized image units "
                "on both adjacent frames."
            ),
            landmark_names=item.landmark_names,
            provisional_score=None,
            warnings=warnings,
        )
        for item in settlements
        if item.side == side
    )


def _ordered_pair(
    bfc: Sequence[ContactCandidate],
    ffc: Sequence[ContactCandidate],
    visual_break_after: Sequence[int],
) -> tuple[ContactCandidate, ContactCandidate] | None:
    if len(bfc) != 1 or len(ffc) != 1:
        return None
    earlier, later = bfc[0], ffc[0]
    if earlier.frame_index >= later.frame_index:
        return None
    if any(earlier.frame_index <= break_after < later.frame_index for break_after in visual_break_after):
        return None
    return earlier, later


def _require_increasing(frames: Sequence[PoseFrame]) -> None:
    for earlier, later in zip(frames, frames[1:]):
        if later.frame_index <= earlier.frame_index:
            raise ContactInputError(
                "Pose frames must be in strictly increasing frame_index order. "
                f"Got {earlier.frame_index} then {later.frame_index}."
            )


def _require_breaks(values: Sequence[int]) -> None:
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContactInputError(
                f"visual_break_after values must be integers >= 0, got {value!r}."
            )


def _result(
    status: str,
    explanation: str,
    settlements: tuple[FootSettlement, ...] = (),
    bfc: tuple[ContactCandidate, ...] = (),
    ffc: tuple[ContactCandidate, ...] = (),
    pair: tuple[ContactCandidate, ContactCandidate] | None = None,
) -> ContactSearchResult:
    return ContactSearchResult(status, explanation, settlements, bfc, ffc, pair)
