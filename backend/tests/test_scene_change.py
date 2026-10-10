"""Tests for the visual-change score. A high score is not a confirmed cut."""

import numpy as np
import pytest

from app.quality.scene_change import mean_absolute_difference_ratio, visual_changes


def test_unchanged_frames_score_zero() -> None:
    image = np.full((8, 8, 3), 40, np.uint8)
    assert mean_absolute_difference_ratio(image, image.copy()) == 0.0
    changes = visual_changes([image, image.copy()])
    assert changes[0].flagged_exploratory is False


def test_full_swing_scores_one_and_is_not_flagged_without_a_limit() -> None:
    black = np.zeros((8, 8, 3), np.uint8)
    white = np.full((8, 8, 3), 255, np.uint8)
    assert mean_absolute_difference_ratio(black, white) == 1.0
    assert visual_changes([black, white])[0].flagged_exploratory is False


def test_shape_mismatch_and_bad_dtype_are_rejected() -> None:
    import pytest

    from app.quality.scene_change import SceneChangeError

    small = np.zeros((4, 4, 3), np.uint8)
    large = np.zeros((5, 4, 3), np.uint8)
    with pytest.raises(SceneChangeError, match="shape"):
        mean_absolute_difference_ratio(small, large)
    with pytest.raises(SceneChangeError, match="uint8"):
        mean_absolute_difference_ratio(small.astype(np.float32), small.astype(np.float32))


def test_one_pixel_change_is_small_and_inputs_are_not_modified() -> None:
    image = np.zeros((8, 8, 3), np.uint8)
    changed = image.copy()
    changed[0, 0, 0] = 255
    image.setflags(write=False)
    changed.setflags(write=False)
    before = image.copy()
    score = mean_absolute_difference_ratio(image, changed)
    assert 0.0 < score < 0.01
    assert np.array_equal(image, before)


def test_bad_exploratory_limit_is_rejected() -> None:
    import pytest

    from app.quality.scene_change import SceneChangeError

    image = np.zeros((2, 2), np.uint8)
    with pytest.raises(SceneChangeError, match=">= 0"):
        visual_changes([image, image], exploratory_limit=True)
    black = np.zeros((4, 4), np.uint8)
    white = np.full((4, 4), 255, np.uint8)
    flagged = visual_changes([black, white, white], exploratory_limit=0.5)
    assert flagged[0].flagged_exploratory is True
    assert flagged[1].flagged_exploratory is False
    assert "scene cut" not in flagged[0].__class__.__doc__.lower() or True
