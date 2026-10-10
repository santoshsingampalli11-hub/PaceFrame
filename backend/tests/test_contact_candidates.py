"""Synthetic fixtures for contact candidates. Not bowling validation."""

import pytest

from app.phases import (
    ContactHeuristicConfig,
    compare_reference_frame,
    search_contact_candidates,
    summarise_comparisons,
)
from app.pose.landmarks import Landmark, PoseFrame


def _frame(index: int, left_x: float | None, right_x: float | None, y: float = 0.8) -> PoseFrame:
    landmarks = {}
    if left_x is not None:
        landmarks["left_ankle"] = Landmark("left_ankle", left_x, y, 1.0, 1.0)
    if right_x is not None:
        landmarks["right_ankle"] = Landmark("right_ankle", right_x, y, 1.0, 1.0)
    return PoseFrame(index, index / 25.0, 200, 100, landmarks)


def _planted() -> list[PoseFrame]:
    # Left ankle still at frames 2-4. Right ankle still at frames 5-7.
    left = [0.0, 0.2, 0.4, 0.4, 0.4, 0.5, 0.7, 0.9]
    right = [0.1, 0.3, 0.5, 0.7, 0.9, 0.9, 0.9, 1.0]
    return [_frame(index, left[index], right[index]) for index in range(8)]


def test_clear_toy_pair_when_sides_are_named() -> None:
    result = search_contact_candidates(
        _planted(),
        ContactHeuristicConfig(stable_displacement=0.001),
        back_foot="left",
        front_foot="right",
    )
    assert result.ordered_pair is not None
    bfc, ffc = result.ordered_pair
    assert bfc.phase_type == "BFC" and bfc.frame_index == 3
    assert ffc.phase_type == "FFC" and ffc.frame_index == 5
    assert bfc.frame_index < ffc.frame_index
    assert bfc.provisional_score is None
    assert "not ground contact" in bfc.warnings[0]


def test_default_config_abstains() -> None:
    result = search_contact_candidates(_planted(), back_foot="left", front_foot="right")
    assert result.status == "abstain"
    assert result.ordered_pair is None
    assert result.bfc_candidates == ()


def test_unnamed_sides_are_not_called_bfc_or_ffc() -> None:
    result = search_contact_candidates(_planted(), ContactHeuristicConfig(0.001))
    assert result.status == "abstain"
    assert result.settlements
    assert result.bfc_candidates == ()


def test_always_moving_feet_abstain() -> None:
    frames = [_frame(index, index * 0.1, 0.2 + index * 0.1) for index in range(6)]
    result = search_contact_candidates(frames, ContactHeuristicConfig(0.001), back_foot="left", front_foot="right")
    assert result.status == "abstain"
    assert result.ordered_pair is None


def test_two_back_foot_pauses_are_ambiguous() -> None:
    left = [0.0, 0.2, 0.2, 0.2, 0.4, 0.5, 0.5, 0.5]
    right = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    frames = [_frame(index, left[index], right[index]) for index in range(8)]
    result = search_contact_candidates(
        frames, ContactHeuristicConfig(0.001), back_foot="left", front_foot="right"
    )
    assert len(result.bfc_candidates) == 2
    assert result.ordered_pair is None
    assert result.status == "ambiguous"


def test_only_one_side_does_not_invent_the_other() -> None:
    frames = [_frame(index, 0.4, 0.1 * index) for index in range(6)]
    result = search_contact_candidates(frames, ContactHeuristicConfig(0.001), back_foot="left", front_foot="right")
    assert result.bfc_candidates
    assert result.ffc_candidates == ()
    assert result.ordered_pair is None


def test_front_foot_before_back_foot_is_not_forced_into_order() -> None:
    left = [0.0, 0.2, 0.4, 0.6, 0.8, 0.8, 0.8, 0.9]
    right = [0.2, 0.2, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0]
    frames = [_frame(index, left[index], min(right[index], 1.0)) for index in range(8)]
    result = search_contact_candidates(
        frames, ContactHeuristicConfig(0.001), back_foot="left", front_foot="right"
    )
    assert result.ordered_pair is None


def test_missing_pose_between_events_blocks_a_pair_when_indices_gap() -> None:
    frames = _planted()
    frames[4] = PoseFrame(4, 4 / 25, 200, 100, {})
    result = search_contact_candidates(
        frames, ContactHeuristicConfig(0.001), back_foot="left", front_foot="right"
    )
    assert result.ordered_pair is None or result.ffc_candidates == ()


def test_visual_break_between_candidates_drops_the_pair() -> None:
    result = search_contact_candidates(
        _planted(),
        ContactHeuristicConfig(0.001),
        back_foot="left",
        front_foot="right",
        visual_break_after=(4,),
    )
    assert result.bfc_candidates and result.ffc_candidates
    assert result.ordered_pair is None


def test_short_sequence_is_insufficient() -> None:
    result = search_contact_candidates([_frame(0, 0.2, 0.3)], ContactHeuristicConfig(0.001))
    assert result.status == "insufficient"


def test_reversed_or_duplicate_frames_are_rejected() -> None:
    from app.phases.contact_candidates import ContactInputError

    planted = _planted()
    with pytest.raises(ContactInputError, match="increasing"):
        search_contact_candidates(
            list(reversed(planted)),
            ContactHeuristicConfig(0.001),
            back_foot="left",
            front_foot="right",
        )
    duplicated = planted[:4] + [planted[3]]
    with pytest.raises(ContactInputError, match="increasing"):
        search_contact_candidates(
            duplicated,
            ContactHeuristicConfig(0.001),
            back_foot="left",
            front_foot="right",
        )


def test_boolean_visual_break_is_rejected() -> None:
    from app.phases.contact_candidates import ContactInputError

    with pytest.raises(ContactInputError, match="visual_break_after"):
        search_contact_candidates(
            _planted(),
            ContactHeuristicConfig(0.001),
            back_foot="left",
            front_foot="right",
            visual_break_after=(True,),
        )


def test_bad_stable_displacement_is_rejected() -> None:
    from app.phases.contact_candidates import ContactInputError

    with pytest.raises(ContactInputError, match=">= 0"):
        ContactHeuristicConfig(stable_displacement=True)
    with pytest.raises(ContactInputError, match=">= 0"):
        ContactHeuristicConfig(stable_displacement=float("nan"))
    with pytest.raises(ContactInputError, match=">= 0"):
        ContactHeuristicConfig(stable_displacement=-0.1)


def test_unknown_phase_type_is_not_silently_dropped() -> None:
    with pytest.raises(ValueError, match="phase_type"):
        compare_reference_frame("bfc", 2, 1)


def test_bad_reference_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="candidate_frame"):
        compare_reference_frame("BFC", True, 1)
    with pytest.raises(ValueError, match="reference_frame"):
        compare_reference_frame("FFC", 1, -2)
    with pytest.raises(ValueError, match="encoded_fps"):
        compare_reference_frame("BFC", 2, 1, encoded_fps=float("inf"))
    both_missing = compare_reference_frame("BFC", None, None)
    assert both_missing.outcome == "abstained"
    assert "Both" in both_missing.note
    empty = summarise_comparisons(())
    assert empty.evaluated == 0
    assert empty.bfc_absolute_errors == ()
    compared = compare_reference_frame("BFC", 12, 10, encoded_fps=25.0)
    assert compared.signed_frame_error == 2
    assert compared.absolute_frame_error == 2
    assert compared.approximate_time_error_seconds == pytest.approx(2 / 25)
    abstained = compare_reference_frame("FFC", None, 20, encoded_fps=25.0)
    missing = compare_reference_frame("BFC", 12, None)
    summary = summarise_comparisons((compared, abstained, missing))
    assert summary.evaluated == 3
    assert summary.abstentions == 1
    assert summary.with_reference == 2
    assert summary.with_candidate == 2
    assert summary.bfc_absolute_errors == (2,)
    assert summary.ffc_absolute_errors == ()
