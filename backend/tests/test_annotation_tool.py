"""Headless tests for the manual annotation tool.

Clips are flat test patterns in a temporary directory, not bowling footage.
The window itself is not opened here.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.annotations.annotate import _handle_key, _parse_args, main
from app.annotations.display import (
    canvas_point_to_normalized,
    draw_landmark_subset,
    draw_manual_markers,
    letterbox_for,
    map_click_to_normalized,
)
from app.annotations.frame_cursor import FrameCursor
from app.annotations.models import AnnotationError, PhaseLabel
from app.annotations.phase_labels import read_phase_labels, write_phase_labels
from app.annotations.session import DeliveryAnnotation
from app.annotations.storage import load_delivery, save_delivery
from app.pose.landmarks import Landmark, PoseFrame
from app.video import VideoReadError

WIDTH = 32
HEIGHT = 24
FPS = 10.0


def _write_clip(path: Path, count: int = 5) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        pytest.skip("This OpenCV build cannot write an MJPG test clip.")
    for index in range(count):
        writer.write(np.full((HEIGHT, WIDTH, 3), index * 40, np.uint8))
    writer.release()


def _session() -> DeliveryAnnotation:
    return DeliveryAnnotation("B01", "D01", labeler="SS")


# --- frames ----------------------------------------------------------------


def test_zero_based_forward_and_backward_navigation(tmp_path: Path) -> None:
    path = tmp_path / "clip.avi"
    _write_clip(path, count=5)
    with FrameCursor(path) as cursor:
        first = cursor.goto(0)
        assert first.index == 0
        assert first.timestamp_seconds == pytest.approx(0.0)
        assert cursor.step(1)
        assert cursor.index == 1
        assert cursor.timestamp_seconds == pytest.approx(1 / FPS)
        assert cursor.goto(4).index == 4
        assert not cursor.step(1)
        assert cursor.index == 4
        revisited = cursor.goto(0).image.copy()
        cursor.goto(3)
        assert np.array_equal(cursor.goto(0).image, revisited)
        assert not cursor.step(-1)
        assert cursor.index == 0


def test_jump_past_the_end_stays_on_the_last_frame(tmp_path: Path) -> None:
    path = tmp_path / "clip.avi"
    _write_clip(path, count=3)
    with FrameCursor(path) as cursor:
        cursor.goto(0)
        with pytest.raises(VideoReadError, match="past the decoded end"):
            cursor.goto(3)
        assert cursor.index == 2
        assert cursor.decoded_count == 3


def test_missing_and_unreadable_video_hide_the_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing.avi"
    with pytest.raises(FileNotFoundError, match="missing.avi") as missing_error:
        FrameCursor(missing)
    assert str(tmp_path) not in str(missing_error.value)

    broken = tmp_path / "broken.avi"
    broken.write_bytes(b"not a video")
    with pytest.raises(VideoReadError, match="broken.avi") as broken_error:
        FrameCursor(broken)
    assert str(tmp_path) not in str(broken_error.value)


def test_reading_frames_does_not_modify_the_video(tmp_path: Path) -> None:
    path = tmp_path / "clip.avi"
    _write_clip(path)
    before = path.read_bytes()
    with FrameCursor(path) as cursor:
        cursor.goto(0)
        cursor.goto(4)
        cursor.goto(1)
    assert path.read_bytes() == before


# --- clicks and aspect ratio ----------------------------------------------


def test_center_click_is_stable_across_aspect_ratios() -> None:
    for image_size, canvas_size in (
        ((1920, 1080), (960, 540)),
        ((1080, 1920), (540, 960)),
        ((640, 480), (800, 800)),
    ):
        image_w, image_h = image_size
        canvas_w, canvas_h = canvas_size
        box = letterbox_for(image_w, image_h, canvas_w, canvas_h)
        click_x = box.pad_x + box.content_width / 2
        click_y = box.pad_y + box.content_height / 2
        mapped = canvas_point_to_normalized(click_x, click_y, box)
        assert mapped is not None
        assert mapped[0] == pytest.approx(0.5, abs=0.02)
        assert mapped[1] == pytest.approx(0.5, abs=0.02)


def test_padding_click_is_ignored() -> None:
    box = letterbox_for(100, 50, 100, 100)
    assert box.pad_y > 0
    assert canvas_point_to_normalized(50, 0, box) is None


def test_window_resize_maps_back_to_the_same_image_point() -> None:
    image_w, image_h = 200, 100
    wide = map_click_to_normalized(100, 50, 200, 100, 200, 100, image_w, image_h)
    square = map_click_to_normalized(200, 200, 400, 400, 400, 400, image_w, image_h)
    assert wide == pytest.approx((0.5, 0.5))
    assert square == pytest.approx((0.5, 0.5))


def test_imshow_click_is_not_scaled_by_a_different_window_rectangle() -> None:
    image_w, image_h = 1080, 1920
    canvas_w, canvas_h = 540, 960
    box = letterbox_for(image_w, image_h, canvas_w, canvas_h)
    click_x = box.pad_x + box.content_width / 2
    click_y = box.pad_y + box.content_height / 2
    direct = canvas_point_to_normalized(click_x, click_y, box)
    refused = map_click_to_normalized(
        click_x,
        click_y,
        int(canvas_w * 1.5),
        int(canvas_h * 1.5),
        canvas_w,
        canvas_h,
        image_w,
        image_h,
    )
    assert direct == pytest.approx((0.5, 0.5), abs=0.02)
    assert refused is None


def test_click_round_trip_for_portrait_and_landscape() -> None:
    from app.annotations.display import normalized_to_canvas_point

    for image_w, image_h, canvas_w, canvas_h in (
        (1080, 1920, 960, 540),
        (1920, 1080, 960, 540),
        (848, 480, 848, 480),
    ):
        box = letterbox_for(image_w, image_h, canvas_w, canvas_h)
        clicks = (
            (box.pad_x + box.content_width / 2, box.pad_y + box.content_height / 2),
            (box.pad_x, box.pad_y),
            (box.pad_x + box.content_width - 1, box.pad_y + box.content_height - 1),
        )
        for click_x, click_y in clicks:
            normalized = canvas_point_to_normalized(click_x, click_y, box)
            assert normalized is not None
            assert 0.0 <= normalized[0] <= 1.0
            assert 0.0 <= normalized[1] <= 1.0
            restored = normalized_to_canvas_point(normalized[0], normalized[1], box)
            assert restored[0] == pytest.approx(click_x)
            assert restored[1] == pytest.approx(click_y)
        assert canvas_point_to_normalized(-1, box.pad_y + 1, box) is None


def test_marker_pixel_follows_the_event_frame_not_the_pose() -> None:
    from app.annotations.display import render_frame

    image = np.zeros((48, 64, 3), np.uint8)
    session = _session()
    session.arm("bfc")
    session.place(2, 0.25, 0.50)
    pose = PoseFrame(
        frame_index=2,
        timestamp_seconds=0.0,
        image_width=64,
        image_height=48,
        landmarks={"left_ankle": Landmark("left_ankle", 0.9, 0.9, 1.0, 1.0)},
    )
    on_event = render_frame(image, 64, 48, session.markers_on_frame(2), pose, [])
    other_frame = render_frame(image, 64, 48, session.markers_on_frame(9), None, [])
    assert on_event[24, 16].tolist() == [0, 215, 255]
    assert other_frame[24, 16].tolist() == [0, 0, 0]
    assert session.markers["bfc"].x_normalized == pytest.approx(0.25)
    assert on_event[43, 58].tolist() != [0, 215, 255]


def test_out_of_range_marker_coordinate_is_rejected() -> None:
    from app.annotations.marker_sidecar import MarkerPosition

    with pytest.raises(AnnotationError, match="0..1"):
        MarkerPosition(
            bowler_id="B01",
            delivery_id="D01",
            event="bfc",
            frame_index=1,
            x_normalized=1.2,
            y_normalized=0.2,
        )
    with pytest.raises(AnnotationError, match="finite"):
        MarkerPosition(
            bowler_id="B01",
            delivery_id="D01",
            event="bfc",
            frame_index=1,
            x_normalized=float("nan"),
            y_normalized=0.2,
        )


def test_manual_marker_is_drawn_at_the_click_not_from_pose() -> None:
    image = np.zeros((30, 40, 3), np.uint8)
    marked = draw_manual_markers(image, {"bfc": (0.25, 0.5)})
    center = marked[15, 10]
    assert center.tolist() == [0, 215, 255]
    pose = PoseFrame(
        frame_index=0,
        timestamp_seconds=0.0,
        image_width=40,
        image_height=30,
        landmarks={},
    )
    untouched = draw_landmark_subset(image, pose)
    assert np.array_equal(untouched, image)


def test_pose_color_presets_keep_coordinates_and_event_colors() -> None:
    from app.annotations.display import (
        EVENT_COLORS,
        POSE_COLOR_PRESETS,
        POSE_FILL_BGR,
        next_pose_color,
        pose_outline_bgr,
        render_frame,
    )

    image = np.full((60, 80, 3), 128, np.uint8)
    pose = PoseFrame(
        frame_index=1,
        timestamp_seconds=0.0,
        image_width=80,
        image_height=60,
        landmarks={"left_ankle": Landmark("left_ankle", 0.5, 0.5, 0.2, 0.2)},
    )
    original_x = pose.landmarks["left_ankle"].x
    color = "black"
    seen = []
    for _ in POSE_COLOR_PRESETS:
        seen.append(color)
        drawn = draw_landmark_subset(image, pose, color)
        assert pose.landmarks["left_ankle"].x == original_x
        assert pose.landmarks["left_ankle"].y == pytest.approx(0.5)
        assert drawn[30, 40].tolist() == list(POSE_FILL_BGR[color])
        color = next_pose_color(color)
    assert seen == list(POSE_COLOR_PRESETS)
    assert next_pose_color("cyan") == "black"
    assert next_pose_color("nope") == "black"
    assert POSE_FILL_BGR["yellow"] == (0, 255, 255)
    assert POSE_FILL_BGR["dark_red"] == (0, 0, 139)
    assert POSE_FILL_BGR["cyan"] == (255, 255, 0)
    assert pose_outline_bgr("black") == (255, 255, 255)
    assert pose_outline_bgr("white") == (0, 0, 0)
    black = draw_landmark_subset(image, pose, "black")
    white = draw_landmark_subset(image, pose, "white")
    assert black[30, 40].tolist() == [0, 0, 0]
    assert white[30, 40].tolist() == [255, 255, 255]
    assert black[27, 40, 0] > 200
    assert white[27, 40, 0] < 80
    hidden = render_frame(image, 80, 60, {}, pose, [], show_raw_pose=False)
    assert hidden[30, 40].tolist() == [128, 128, 128]
    missing = draw_landmark_subset(image, None)
    assert np.array_equal(missing, image)
    event = draw_manual_markers(image, {"bfc": (0.5, 0.5)})
    assert event[30, 40].tolist() == list(EVENT_COLORS["bfc"])


def test_pose_dots_do_not_assign_events() -> None:
    image = np.zeros((20, 20, 3), np.uint8)
    pose = PoseFrame(
        frame_index=3,
        timestamp_seconds=0.1,
        image_width=20,
        image_height=20,
        landmarks={"left_ankle": Landmark("left_ankle", 0.5, 0.5, 1.0, 1.0)},
    )
    session = _session()
    drawn = draw_landmark_subset(image, pose)
    assert drawn[7, 10].any()
    assert not drawn[10, 10].any()
    assert session.bfc_frame is None
    assert session.ffc_frame is None
    assert session.release_frame is None
    assert session.markers == {}


# --- session and files -----------------------------------------------------


def test_new_session_has_no_guessed_events() -> None:
    session = _session()
    assert session.to_phase_label() == PhaseLabel(bowler_id="B01", delivery_id="D01", labeler="SS")


def test_place_clear_and_replace_marker() -> None:
    session = _session()
    session.arm("bfc")
    session.place(4, 0.2, 0.7)
    session.place(8, 0.4, 0.6)
    marker = session.markers["bfc"]
    assert session.bfc_frame == 8
    assert marker.frame_index == 8
    assert marker.x_normalized == pytest.approx(0.4)
    assert marker.y_normalized == pytest.approx(0.6)
    assert session.clear("bfc")
    assert session.bfc_frame is None
    assert "bfc" not in session.markers


def test_equal_event_frames_do_not_change_the_session() -> None:
    session = _session()
    session.arm("bfc")
    session.place(10, 0.2, 0.2)
    session.arm("ffc")
    with pytest.raises(AnnotationError, match="earlier"):
        session.place(10, 0.3, 0.3)
    assert session.ffc_frame is None
    assert "ffc" not in session.markers
    assert session.bfc_frame == 10


def test_partial_annotation_round_trip_preserves_other_deliveries(tmp_path: Path) -> None:
    labels = tmp_path / "phase_labels.csv"
    markers = tmp_path / "marker_positions.csv"
    other = PhaseLabel(bowler_id="B02", delivery_id="D01", bfc_frame=1, ffc_frame=2, release_frame=3)
    write_phase_labels(labels, [other])

    session = _session()
    session.arm("bfc")
    session.place(12, 0.25, 0.8)
    save_delivery(session, labels, markers)

    stored = read_phase_labels(labels)
    assert [label.key for label in stored] == [("B02", "D01"), ("B01", "D01")]
    assert stored[1].bfc_frame == 12
    assert stored[1].ffc_frame is None
    assert stored[1].release_frame is None

    reloaded = _session()
    warnings = load_delivery(reloaded, labels, markers)
    assert warnings == []
    assert reloaded.bfc_frame == 12
    assert reloaded.markers["bfc"].x_normalized == pytest.approx(0.25)
    assert reloaded.dirty is False
    assert read_phase_labels(labels)[0] == other


def test_mismatched_marker_frame_is_not_restored(tmp_path: Path) -> None:
    labels = tmp_path / "phase_labels.csv"
    markers = tmp_path / "marker_positions.csv"
    session = _session()
    session.arm("bfc")
    session.place(5, 0.2, 0.2)
    save_delivery(session, labels, markers)
    text = markers.read_text(encoding="utf-8")
    markers.write_text(text.replace(",5,", ",9,"), encoding="utf-8")

    reloaded = _session()
    warnings = load_delivery(reloaded, labels, markers)
    assert reloaded.bfc_frame == 5
    assert reloaded.markers == {}
    assert warnings
    assert reloaded.dirty is False


def test_arming_an_event_does_not_assign_its_frame(tmp_path: Path) -> None:
    path = tmp_path / "clip.avi"
    _write_clip(path, count=2)
    session = _session()
    with FrameCursor(path) as cursor:
        cursor.goto(1)
        mode, _jump, status, playing = _handle_key(
            ord("1"),
            "view",
            "",
            "",
            False,
            cursor,
            session,
            _PoseStub(),
            tmp_path / "labels.csv",
            tmp_path / "markers.csv",
        )
    assert mode == "view"
    assert playing is False
    assert "BFC" in status
    assert session.bfc_frame is None
    assert not (tmp_path / "labels.csv").exists()


class _PoseStub:
    message = "pose off"

    def toggle(self) -> str:
        return self.message


def test_label_and_marker_output_paths_are_independent() -> None:
    args = _parse_args(
        [
            "--video",
            "clip.mp4",
            "--bowler",
            "TEST01",
            "--delivery",
            "D01",
            "--labeler",
            "TEST",
            "--labels",
            "annotation_smoke_test/test_phase_labels.csv",
            "--markers",
            "annotation_smoke_test/test_marker_positions.csv",
        ]
    )
    assert args.labels != args.markers
    assert args.labels.name == "test_phase_labels.csv"
    assert args.markers.name == "test_marker_positions.csv"
    assert args.bowler == "TEST01"
    assert args.labeler == "TEST"


def test_marker_write_failure_leaves_the_delivery_unsaved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    labels = tmp_path / "phase_labels.csv"
    markers = tmp_path / "marker_positions.csv"
    other = PhaseLabel(bowler_id="B02", delivery_id="D09", bfc_frame=1, ffc_frame=2, release_frame=3)
    write_phase_labels(labels, [other])
    session = _session()
    session.arm("bfc")
    session.place(4, 0.2, 0.3)

    def fail_markers(*_args: object, **_kwargs: object) -> None:
        raise AnnotationError("Could not write marker_positions.csv.")

    monkeypatch.setattr("app.annotations.storage.replace_delivery_markers", fail_markers)
    with pytest.raises(AnnotationError, match="still unsaved"):
        save_delivery(session, labels, markers)

    assert session.dirty is True
    assert not markers.exists()
    stored = read_phase_labels(labels)
    assert stored[0] == other
    assert stored[1].key == ("B01", "D01")
    assert stored[1].bfc_frame == 4


def test_unsaved_foot_correction_blocks_quit(tmp_path: Path) -> None:
    from app.annotations.foot_corrections import FootReview

    path = tmp_path / "clip.avi"
    _write_clip(path, count=2)
    session = _session()
    feet = FootReview("a" * 64, "B01", "D01")
    feet.place(0, 0.2, 0.3)
    with FrameCursor(path) as cursor:
        mode, _jump, status, playing = _handle_key(
            ord("q"),
            "view",
            "",
            "",
            False,
            cursor,
            session,
            _PoseStub(),
            tmp_path / "phase_labels.csv",
            tmp_path / "marker_positions.csv",
            feet=feet,
        )
    assert mode == "confirm_quit"
    assert playing is False
    assert session.dirty is False
    assert feet.dirty is True
    assert status == ""


def test_failed_foot_write_keeps_the_delivery_unsaved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.annotations.foot_corrections import FootCorrectionError, FootReview

    path = tmp_path / "clip.avi"
    _write_clip(path, count=2)
    session = _session()
    session.arm("bfc")
    session.place(0, 0.2, 0.2)
    feet = FootReview("b" * 64, "B01", "D01")
    feet.place(0, 0.4, 0.5)

    def fail_feet(*_args: object, **_kwargs: object) -> None:
        raise FootCorrectionError("Could not write foot_corrections.csv.")

    monkeypatch.setattr("app.annotations.annotate.replace_delivery_foot_corrections", fail_feet)
    with FrameCursor(path) as cursor:
        mode, _jump, status, playing = _handle_key(
            ord("y"),
            "confirm_save",
            "",
            "",
            False,
            cursor,
            session,
            _PoseStub(),
            tmp_path / "phase_labels.csv",
            tmp_path / "marker_positions.csv",
            feet=feet,
            foot_path=tmp_path / "foot_corrections.csv",
        )
        quit_mode, _quit_jump, _quit_status, _quit_playing = _handle_key(
            ord("q"),
            mode,
            "",
            status,
            playing,
            cursor,
            session,
            _PoseStub(),
            tmp_path / "phase_labels.csv",
            tmp_path / "marker_positions.csv",
            feet=feet,
            foot_path=tmp_path / "foot_corrections.csv",
        )
    assert "Saved phase frames" not in status
    assert "foot corrections were not" in status
    assert session.dirty is True
    assert feet.dirty is True
    assert quit_mode == "confirm_quit"
    assert not (tmp_path / "foot_corrections.csv").exists()


def test_failed_foot_write_can_be_retried_and_reloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.annotations.annotate import _hud, _unsaved
    from app.annotations.foot_corrections import FootCorrectionError, FootReview, load_foot_corrections
    from app.annotations.marker_sidecar import read_marker_positions
    from app.annotations.phase_labels import read_phase_labels
    import app.annotations.annotate as annotate_module

    path = tmp_path / "clip.avi"
    _write_clip(path, count=2)
    labels = tmp_path / "phase_labels.csv"
    markers = tmp_path / "marker_positions.csv"
    foot_path = tmp_path / "foot_corrections.csv"
    session = _session()
    session.arm("bfc")
    session.place(0, 0.2, 0.2)
    feet = FootReview("c" * 64, "B01", "D01")
    feet.place(0, 0.4, 0.5)
    real_write = annotate_module.replace_delivery_foot_corrections
    attempts = {"count": 0}

    def fail_once(*args: object, **kwargs: object) -> object:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise FootCorrectionError("Could not write foot_corrections.csv.")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(annotate_module, "replace_delivery_foot_corrections", fail_once)
    with FrameCursor(path) as cursor:
        _mode, _jump, status, playing = _handle_key(
            ord("y"),
            "confirm_save",
            "",
            "",
            False,
            cursor,
            session,
            _PoseStub(),
            labels,
            markers,
            feet=feet,
            foot_path=foot_path,
        )
        hud = " ".join(
            _hud(cursor, session, "pose off", "view", "", status, unsaved=_unsaved(session, feet))
        )
        quit_mode, _quit_jump, _quit_status, _quit_playing = _handle_key(
            ord("q"),
            "view",
            "",
            status,
            playing,
            cursor,
            session,
            _PoseStub(),
            labels,
            markers,
            feet=feet,
            foot_path=foot_path,
        )
        stored_labels = read_phase_labels(labels)
        stored_markers = read_marker_positions(markers)
        assert stored_labels[0].bfc_frame == 0
        assert stored_markers[0].event == "bfc"
        assert stored_markers[0].frame_index == 0
        assert stored_markers[0].x_normalized == pytest.approx(0.2)
        assert "unsaved" in hud
        assert quit_mode == "confirm_quit"
        assert not foot_path.exists()

        retry_mode, _retry_jump, retry_status, _retry_playing = _handle_key(
            ord("y"),
            "confirm_save",
            "",
            "",
            False,
            cursor,
            session,
            _PoseStub(),
            labels,
            markers,
            feet=feet,
            foot_path=foot_path,
        )
    assert retry_mode == "view"
    assert "Saved phase frames" in retry_status
    assert session.dirty is False
    assert feet.dirty is False
    assert attempts["count"] == 2

    reloaded = _session()
    load_delivery(reloaded, labels, markers)
    reloaded_feet, warnings = load_foot_corrections(foot_path, "c" * 64, "B01", "D01")
    assert warnings == []
    assert reloaded.bfc_frame == 0
    assert reloaded.markers["bfc"].x_normalized == pytest.approx(0.2)
    assert reloaded.markers["bfc"].y_normalized == pytest.approx(0.2)
    assert len(reloaded_feet) == 1
    assert reloaded_feet[0].landmark_name == "left_ankle"
    assert reloaded_feet[0].frame_index == 0
    assert reloaded_feet[0].x_normalized == pytest.approx(0.4)
    assert reloaded_feet[0].y_normalized == pytest.approx(0.5)


def test_failed_save_confirmation_is_not_reported_as_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "clip.avi"
    _write_clip(path, count=2)
    session = _session()
    session.arm("bfc")
    session.place(0, 0.2, 0.2)

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise AnnotationError("Phase frames were written, but marker positions were not.")

    monkeypatch.setattr("app.annotations.annotate.save_delivery", fail_save)
    with FrameCursor(path) as cursor:
        mode, _jump, status, playing = _handle_key(
            ord("y"),
            "confirm_save",
            "",
            "",
            False,
            cursor,
            session,
            _PoseStub(),
            tmp_path / "phase_labels.csv",
            tmp_path / "marker_positions.csv",
        )
    assert mode == "view"
    assert playing is False
    assert "Saved phase frames" not in status
    assert "marker positions were not" in status
    assert session.dirty is True


def test_a_click_is_kept_on_the_frame_that_is_showing() -> None:
    from app.annotations.annotate import _playback_should_advance

    assert _playback_should_advance(-1, pending_clicks=False, playing=True) is True
    assert _playback_should_advance(-1, pending_clicks=True, playing=True) is False
    assert _playback_should_advance(ord("d"), pending_clicks=False, playing=False) is False


def test_labels_from_another_video_are_not_loaded(tmp_path: Path) -> None:
    from app.annotations.video_identity import lookup_video_filename

    labels = tmp_path / "phase_labels.csv"
    markers = tmp_path / "marker_positions.csv"
    session = _session()
    session.arm("bfc")
    session.place(3, 0.2, 0.4)
    save_delivery(session, labels, markers, "first.mp4")
    assert lookup_video_filename(labels, "B01", "D01") == "first.mp4"

    other = DeliveryAnnotation("B01", "D01")
    assert lookup_video_filename(labels, "B01", "D01") != "second.mp4"
    loaded = DeliveryAnnotation("B01", "D01")
    load_delivery(loaded, labels, markers)
    assert loaded.bfc_frame == 3
    blocked = lookup_video_filename(labels, "B01", "D01")
    assert blocked == "first.mp4"
    assert blocked != "second.mp4"
    fresh = DeliveryAnnotation("B01", "D01")
    assert fresh.bfc_frame is None


def test_save_is_blocked_until_mismatched_labels_are_accepted(tmp_path: Path) -> None:
    path = tmp_path / "clip.avi"
    _write_clip(path, count=2)
    session = _session()
    accepted = [False]
    with FrameCursor(path) as cursor:
        mode, _jump, status, playing = _handle_key(
            ord("y"),
            "confirm_save",
            "",
            "",
            False,
            cursor,
            session,
            _PoseStub(),
            tmp_path / "phase_labels.csv",
            tmp_path / "marker_positions.csv",
            "second.mp4",
            accepted,
        )
    assert mode == "view"
    assert playing is False
    assert "Not saved" in status
    assert accepted == [False]
    assert not (tmp_path / "phase_labels.csv").exists()


def test_main_rejects_a_missing_video_without_a_directory_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "--video",
            str(tmp_path / "no.avi"),
            "--bowler",
            "B01",
            "--delivery",
            "D01",
            "--labels",
            str(tmp_path / "phase_labels.csv"),
            "--markers",
            str(tmp_path / "marker_positions.csv"),
        ]
    )
    assert code == 1
    message = capsys.readouterr().out
    assert "no.avi" in message
    assert str(tmp_path) not in message
