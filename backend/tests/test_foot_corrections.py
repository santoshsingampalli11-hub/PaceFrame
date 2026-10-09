"""Tests for manual foot-landmark corrections. No video model and no GUI."""

import hashlib
from pathlib import Path

import numpy as np
import pytest

from app.annotations.foot_corrections import (
    FOOT_LANDMARKS,
    FootCorrection,
    FootCorrectionError,
    FootReview,
    choose_foot_point,
    consecutive_foot_shift,
    file_sha256,
    load_foot_corrections,
    read_foot_corrections,
    replace_delivery_foot_corrections,
)
from app.annotations.session import DeliveryAnnotation
from app.pose.landmarks import Landmark, PoseFrame

SHA = "a" * 64
OTHER = "b" * 64


def _review() -> FootReview:
    return FootReview(SHA, "B01", "D01")


def _pose(index: int, ankle: tuple[float, float] | None) -> PoseFrame:
    landmarks = {}
    if ankle is not None:
        landmarks["left_ankle"] = Landmark("left_ankle", ankle[0], ankle[1], 0.99, 0.99)
    return PoseFrame(
        frame_index=index,
        timestamp_seconds=index / 30,
        image_width=100,
        image_height=80,
        landmarks=landmarks,
    )


def test_each_foot_landmark_can_be_selected() -> None:
    review = _review()
    seen = []
    for _ in FOOT_LANDMARKS:
        seen.append(review.cycle(1))
    assert set(seen) == set(FOOT_LANDMARKS)
    assert "left_ankle" in seen and "right_foot_index" in seen


def test_correction_stays_on_its_frame_and_can_be_replaced_or_removed() -> None:
    review = _review()
    review.cycle(1)
    assert review.selected() == "right_ankle"
    review.index = 0
    review.place(7, 0.25, 0.8)
    review.place(7, 0.30, 0.82)
    assert review.on_frame(7)["left_ankle"] == pytest.approx((0.30, 0.82))
    assert review.on_frame(8) == {}
    assert review.clear_selected(7)
    assert review.on_frame(7) == {}
    pose = _pose(7, (0.1, 0.1))
    assert pose.landmarks["left_ankle"].x == pytest.approx(0.1)


def test_manual_point_is_not_mixed_with_the_raw_point() -> None:
    raw = (0.2, 0.3)
    correction = (0.4, 0.5)
    assert choose_foot_point(raw, correction, use_correction=False) == raw
    assert choose_foot_point(raw, correction, use_correction=True) == correction
    assert choose_foot_point(raw, None, use_correction=True) is None


def test_consecutive_shift_is_absent_when_a_point_or_frame_is_missing() -> None:
    first = _pose(4, (0.2, 0.2))
    second = _pose(5, (0.2, 0.5))
    jumped = _pose(7, (0.2, 0.5))
    assert consecutive_foot_shift(first, second, "left_ankle") == pytest.approx(0.3)
    assert consecutive_foot_shift(first, jumped, "left_ankle") is None
    assert consecutive_foot_shift(first, _pose(5, None), "left_ankle") is None


def test_event_markers_are_unchanged_by_a_foot_correction() -> None:
    session = DeliveryAnnotation("B01", "D01")
    session.arm("bfc")
    session.place(3, 0.4, 0.9)
    review = _review()
    review.place(3, 0.2, 0.7)
    assert session.bfc_frame == 3
    assert session.markers["bfc"].x_normalized == pytest.approx(0.4)
    assert session.to_phase_label().ffc_frame is None


def test_save_reload_and_other_video_rows(tmp_path: Path) -> None:
    path = tmp_path / "foot_corrections.csv"
    review = _review()
    review.place(4, 0.2, 0.6)
    other = FootCorrection(OTHER, "B09", "D09", 1, "left_heel", 0.1, 0.2)
    replace_delivery_foot_corrections(path, SHA, "B01", "D01", list(review.items.values()))
    replace_delivery_foot_corrections(path, OTHER, "B09", "D09", [other])
    loaded, warnings = load_foot_corrections(path, SHA, "B01", "D01")
    assert warnings
    assert "another video" in warnings[0]
    assert len(loaded) == 1
    assert loaded[0].landmark_name == "left_ankle"
    assert loaded[0].frame_index == 4
    assert loaded[0].correction_source == "manual"
    again = read_foot_corrections(path)
    assert len(again) == 2


def test_hash_mismatch_does_not_return_those_rows(tmp_path: Path) -> None:
    path = tmp_path / "foot_corrections.csv"
    row = FootCorrection(SHA, "B01", "D01", 2, "right_heel", 0.5, 0.5)
    replace_delivery_foot_corrections(path, SHA, "B01", "D01", [row])
    loaded, warnings = load_foot_corrections(path, OTHER, "B01", "D01")
    assert loaded == ()
    assert warnings


def test_duplicate_and_invalid_corrections_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(FootCorrectionError, match="0..1"):
        FootCorrection(SHA, "B01", "D01", 1, "left_ankle", 1.4, 0.2)
    path = tmp_path / "broken.csv"
    path.write_text("video_sha256,bowler_id\n", encoding="utf-8")
    with pytest.raises(FootCorrectionError, match="header"):
        read_foot_corrections(path)
    row = FootCorrection(SHA, "B01", "D01", 1, "left_ankle", 0.2, 0.2)
    with pytest.raises(FootCorrectionError, match="Duplicate"):
        replace_delivery_foot_corrections(tmp_path / "ok.csv", SHA, "B01", "D01", [row, row])


def test_missing_video_hash_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        file_sha256(tmp_path / "missing.mp4")


def test_file_hash_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "clip.bin"
    path.write_bytes(b"abc")
    assert file_sha256(path) == hashlib.sha256(b"abc").hexdigest()


def test_outline_and_correction_are_different_marks() -> None:
    from app.annotations.display import draw_foot_corrections, draw_landmark_subset, draw_manual_markers

    image = np.zeros((40, 40, 3), np.uint8)
    pose = PoseFrame(
        frame_index=1,
        timestamp_seconds=0.0,
        image_width=40,
        image_height=40,
        landmarks={"left_ankle": Landmark("left_ankle", 0.5, 0.5, 0.99, 0.99)},
    )
    raw = draw_landmark_subset(image, pose)
    corrected = draw_foot_corrections(image, {"left_ankle": (0.2, 0.2)})
    event = draw_manual_markers(image, {"bfc": (0.8, 0.8)})
    assert raw[20, 20].tolist() == [0, 0, 0]
    assert corrected[8, 8, 0] > 200
    assert event[32, 32].tolist() == [0, 215, 255]
