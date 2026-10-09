"""Tests for mapping a pose crop back to the original frame. No model is loaded."""

import pytest

from app.annotations.pose_crop import (
    PoseCropError,
    crop_point_to_full_frame,
    pixel_crop,
    remap_pose_to_full_frame,
)
from app.annotations.session import DeliveryAnnotation
from app.pose.landmarks import Landmark, PoseFrame


def test_crop_center_maps_to_the_full_frame() -> None:
    crop = pixel_crop(100, 40, 500, 440, 848, 480)
    x_norm, y_norm = crop_point_to_full_frame(0.5, 0.5, crop, 848, 480)
    assert x_norm == pytest.approx(300 / 848)
    assert y_norm == pytest.approx(240 / 480)


def test_crop_corner_maps_without_swapping_axes() -> None:
    crop = pixel_crop(200, 100, 600, 900, 1080, 1920)
    x_norm, y_norm = crop_point_to_full_frame(0.0, 1.0, crop, 1080, 1920)
    assert x_norm == pytest.approx(200 / 1080)
    assert y_norm == pytest.approx(900 / 1920)


def test_crop_outside_the_image_is_rejected() -> None:
    with pytest.raises(PoseCropError, match="inside"):
        pixel_crop(-10, 0, 100, 100, 848, 480)


def test_tiny_crop_is_rejected() -> None:
    with pytest.raises(PoseCropError, match="32"):
        pixel_crop(0, 0, 10, 100, 848, 480)


def test_remapped_pose_does_not_move_a_manual_marker() -> None:
    crop = pixel_crop(100, 50, 300, 250, 640, 480)
    pose = PoseFrame(
        frame_index=4,
        timestamp_seconds=0.1,
        image_width=200,
        image_height=200,
        landmarks={"left_ankle": Landmark("left_ankle", 0.0, 0.0, 0.99, 0.99)},
    )
    remapped = remap_pose_to_full_frame(pose, crop, 640, 480)
    session = DeliveryAnnotation("B01", "D01")
    session.arm("bfc")
    session.place(4, 0.2, 0.8)
    assert remapped.landmarks["left_ankle"].x == pytest.approx(100 / 640)
    assert remapped.landmarks["left_ankle"].y == pytest.approx(50 / 480)
    assert remapped.image_width == 640
    assert session.markers["bfc"].x_normalized == pytest.approx(0.2)
    assert session.bfc_frame == 4
