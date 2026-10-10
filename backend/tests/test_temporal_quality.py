"""Tests for temporal pose diagnostics. No quality grades are assigned."""

import pytest

from app.pose.landmarks import Landmark, PoseFrame
from app.quality.temporal import (
    continuity_notes,
    exploratory_large_steps,
    landmark_deviations,
    landmark_steps,
)


def _frame(index: int, x: float | None, *, width: int = 100, height: int = 50) -> PoseFrame:
    landmarks = {}
    if x is not None:
        landmarks["left_ankle"] = Landmark("left_ankle", x, 0.2, 1.0, 1.0)
    return PoseFrame(index, index / 30.0, width, height, landmarks)


def test_stationary_landmark_has_zero_step_and_zero_deviation() -> None:
    frames = [_frame(0, 0.4), _frame(1, 0.4), _frame(2, 0.4)]
    steps = landmark_steps(frames)
    assert steps[0].normalized_displacement == pytest.approx(0.0)
    assert landmark_deviations(frames)[0].normalized_deviation == pytest.approx(0.0)


def test_smooth_motion_has_zero_chord_deviation() -> None:
    frames = [_frame(0, 0.0), _frame(1, 0.2), _frame(2, 0.4)]
    assert landmark_steps(frames)[0].normalized_displacement == pytest.approx(0.2)
    assert landmark_deviations(frames)[0].normalized_deviation == pytest.approx(0.0)


def test_sudden_return_is_a_large_deviation_not_a_grade() -> None:
    frames = [_frame(0, 0.0), _frame(1, 0.5), _frame(2, 0.0)]
    deviation = landmark_deviations(frames)[0]
    assert deviation.frame_index == 1
    assert deviation.normalized_deviation == pytest.approx(0.5)
    assert exploratory_large_steps(landmark_steps(frames), None) == ()


def test_missing_landmark_is_not_bridged() -> None:
    frames = [_frame(0, 0.1), _frame(1, None), _frame(2, 0.9)]
    assert landmark_steps(frames) == ()
    assert landmark_deviations(frames) == ()


def test_missing_pose_is_listed_and_not_bridged() -> None:
    frames = [_frame(0, 0.1), _frame(1, None), _frame(2, 0.4)]
    notes = continuity_notes(frames)
    assert notes.missing_pose_frame_indices == (1,)
    assert notes.largest_steps == ()
    assert "do not identify the bowler" in notes.note


def test_frame_index_gap_is_not_treated_as_consecutive() -> None:
    frames = [_frame(0, 0.0), _frame(2, 0.5)]
    assert landmark_steps(frames) == ()


def test_empty_and_single_frame_have_no_steps() -> None:
    assert landmark_steps(()) == ()
    assert landmark_steps((_frame(0, 0.2),)) == ()
    assert continuity_notes(()).largest_steps == ()


def test_normalized_step_ignores_image_pixel_size() -> None:
    wide = landmark_steps([_frame(0, 0.0, width=1920, height=1080), _frame(1, 0.1, width=1920, height=1080)])
    tall = landmark_steps([_frame(0, 0.0, width=1080, height=1920), _frame(1, 0.1, width=1080, height=1920)])
    assert wide[0].normalized_displacement == pytest.approx(tall[0].normalized_displacement)


def test_reversed_and_duplicate_indices_are_rejected() -> None:
    from app.quality.temporal import TemporalSequenceError

    with pytest.raises(TemporalSequenceError, match="increasing"):
        landmark_steps([_frame(2, 0.1), _frame(1, 0.2)])
    with pytest.raises(TemporalSequenceError, match="increasing"):
        landmark_deviations([_frame(1, 0.1), _frame(1, 0.2), _frame(2, 0.3)])


def test_negative_exploratory_limit_is_rejected() -> None:
    from app.quality.temporal import TemporalSequenceError

    with pytest.raises(TemporalSequenceError, match=">= 0"):
        exploratory_large_steps((), -0.1)
    with pytest.raises(TemporalSequenceError, match="number"):
        exploratory_large_steps((), True)
    steps = landmark_steps([_frame(0, 0.0), _frame(1, 0.4)])
    assert exploratory_large_steps(steps, None) == ()
    assert len(exploratory_large_steps(steps, 0.3)) == 1
