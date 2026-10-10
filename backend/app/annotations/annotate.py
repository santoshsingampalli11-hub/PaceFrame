"""Local window for marking BFC, FFC, and release on a real bowling video.

The picture in the window is a decoded frame from the file you pass in.
Nothing in this tool detects those events or draws a substitute bowler.

From the ``backend`` directory:

    python -m app.annotations.annotate --video path\\to\\delivery.mp4 --bowler B01 --delivery D01 --labeler SS

Controls:

- Right arrow or D: next frame
- Left arrow or A: previous frame
- G, then digits, then Enter: jump to a zero-based frame
- 1 / 2 / 3: select BFC, FFC, or Release
- Left click on the bowler: store that event on the current frame at the click
- C: clear the selected event
- R, then drag: limit pose dots to a box you draw around the bowler. This is not tracking.
- U: clear that pose box and use the full frame again
- T: toggle the optional MediaPipe landmark overlay
- Space: play or pause
- L: load labels that were saved for a different video name, after you mean to
- S, then Y: save phase frames, marker clicks, and manual foot corrections
- Q or Esc: quit; if phase labels or foot corrections are unsaved, Y confirms discard

Clicks in the black bars around the frame are ignored. The original video
file is never written.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from app.annotations.display import (
    EVENT_LABELS,
    canvas_point_to_normalized,
    letterbox_for,
    next_pose_color,
    render_frame,
)
from app.annotations.foot_corrections import (
    FOOT_LABELS,
    FootCorrectionError,
    FootReview,
    consecutive_foot_shift,
    file_sha256,
    load_foot_corrections,
    replace_delivery_foot_corrections,
)
from app.annotations.frame_cursor import FrameCursor
from app.annotations.models import AnnotationError
from app.annotations.session import DeliveryAnnotation
from app.annotations.storage import load_delivery, save_delivery
from app.annotations.video_identity import lookup_video_filename
from app.annotations.pose_crop import PixelCrop, PoseCropError, pixel_crop, remap_pose_to_full_frame
from app.video import VideoFrame, VideoReadError

WINDOW = "Fast Bowling manual annotation"
HELP = (
    "gold BFC, green FFC, magenta RELEASE are clicks; small dots are unverified pose  |  "
    "1/2/3 select  click place  c clear  t pose  g jump  arrows step  space play  s save  q quit"
)
_RIGHT_KEYS = {ord("d"), ord("D"), 2555904, 0x270000, 65363}
_LEFT_KEYS = {ord("a"), ord("A"), 2424832, 0x250000, 65361}

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LABELS = _REPO_ROOT / "fast_bowling_dataset" / "phase_labels" / "phase_labels.csv"
DEFAULT_MARKERS = _REPO_ROOT / "fast_bowling_dataset" / "phase_labels" / "marker_positions.csv"
DEFAULT_FOOT = Path(__file__).resolve().parents[2] / "debug_output" / "foot_corrections.csv"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        session = DeliveryAnnotation(args.bowler, args.delivery, args.labeler, args.notes)
    except AnnotationError as error:
        print(error)
        return 1
    cursor: FrameCursor | None = None
    try:
        cursor = FrameCursor(args.video)
        cursor.goto(0)
        video_name = args.video.name
        stored_video = lookup_video_filename(args.labels, session.bowler_id, session.delivery_id)
        if stored_video is not None and stored_video != video_name:
            warnings = [
                f"Not loaded. {session.bowler_id}/{session.delivery_id} was saved for "
                f"{stored_video}, not {video_name}. Press L to load those labels."
            ]
            accept_saved_labels = False
        else:
            warnings = load_delivery(session, args.labels, args.markers)
            if stored_video is None and (session.bfc_frame is not None or session.markers):
                warnings.append(
                    "These labels have no saved video name. They may belong to another file."
                )
            accept_saved_labels = True
        video_sha = file_sha256(args.video)
        feet = FootReview(video_sha, session.bowler_id, session.delivery_id)
        loaded_feet, foot_warnings = load_foot_corrections(
            args.foot_corrections, video_sha, session.bowler_id, session.delivery_id
        )
        for item in loaded_feet:
            feet.items[(item.frame_index, item.landmark_name)] = item
        warnings.extend(foot_warnings)
    except (FileNotFoundError, VideoReadError, AnnotationError, FootCorrectionError, OSError) as error:
        if cursor is not None:
            cursor.close()
        print(error)
        return 1
    for warning in warnings:
        print(warning)
    print(
        f"Opened {video_name} for {session.bowler_id}/{session.delivery_id}. "
        "Events are marked by hand; they are not detected."
    )
    try:
        _run_window(
            cursor,
            session,
            args.labels,
            args.markers,
            video_name,
            accept_saved_labels,
            warnings[-1] if warnings else "",
            feet,
            args.foot_corrections,
        )
    finally:
        cursor.close()
        cv2.destroyAllWindows()
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mark BFC, FFC, and release by hand on a real bowling video."
    )
    parser.add_argument("--video", required=True, type=Path, help="Local bowling video to display.")
    parser.add_argument("--bowler", required=True, help="Anonymous bowler id, for example B01.")
    parser.add_argument("--delivery", required=True, help="Anonymous delivery id, for example D01.")
    parser.add_argument("--labeler", default="", help="Initials or role. Optional.")
    parser.add_argument("--notes", default="", help="Optional note stored with the phase label.")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS, help="Phase-label CSV.")
    parser.add_argument("--markers", type=Path, default=DEFAULT_MARKERS, help="Marker-position CSV.")
    parser.add_argument(
        "--foot-corrections",
        type=Path,
        default=DEFAULT_FOOT,
        help="Sidecar for manual foot-landmark clicks. Raw pose output is not written here.",
    )
    return parser.parse_args(argv)


def _run_window(
    cursor: FrameCursor,
    session: DeliveryAnnotation,
    labels_path: Path,
    markers_path: Path,
    video_filename: str,
    accept_saved_labels: bool,
    initial_status: str = "",
    feet: FootReview | None = None,
    foot_path: Path | None = None,
) -> None:
    try:
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    except cv2.error:
        print("OpenCV cannot open a display window on this machine.")
        return

    window_w, window_h = _initial_window_size(cursor.metadata.width, cursor.metadata.height)
    cv2.resizeWindow(WINDOW, window_w, window_h)
    clicks: list[tuple[int, int]] = []
    drag: dict[str, tuple[int, int] | None] = {"start": None, "end": None}
    roi_mode = [False]
    roi_done = [False]
    pose_crop: list[PixelCrop | None] = [None]

    def on_mouse(event: int, x: int, y: int, _flags: int, _param: object) -> None:
        if roi_mode[0]:
            if event == cv2.EVENT_LBUTTONDOWN:
                drag["start"] = (x, y)
                drag["end"] = (x, y)
            elif event == cv2.EVENT_MOUSEMOVE and drag["start"] is not None:
                drag["end"] = (x, y)
            elif event == cv2.EVENT_LBUTTONUP and drag["start"] is not None:
                drag["end"] = (x, y)
                roi_done[0] = True
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            clicks.append((x, y))

    cv2.setMouseCallback(WINDOW, on_mouse)
    pose = _PoseToggle()
    mode = "view"
    jump_text = ""
    status = initial_status
    playing = False
    shown = (window_w, window_h)
    started = False
    accepted = [accept_saved_labels]
    previous_pose: list[object | None] = [None]
    pose_color = ["black"]

    try:
        while True:
            if started and cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                if _unsaved(session, feet):
                    print("Window closed. Unsaved annotations were NOT written.")
                break
            frame = cursor.current()
            pose_frame = pose.estimate(frame, pose_crop[0]) if pose.enabled else None
            foot_layer = {}
            if feet is not None and feet.show_corrected:
                foot_layer = feet.on_frame(frame.index)
            foot_note = ""
            if feet is not None and feet.active:
                shift = consecutive_foot_shift(previous_pose[0], pose_frame, feet.selected())  # type: ignore[arg-type]
                if shift is not None:
                    foot_note = (
                        f"{FOOT_LABELS[feet.selected()]} moved {shift:.3f} of the image "
                        "since the previous frame. Not a quality score."
                    )
                else:
                    foot_note = f"Correcting {FOOT_LABELS[feet.selected()]}. Leave it unset if the point is unclear."
            if pose_frame is not None:
                previous_pose[0] = pose_frame
            canvas = render_frame(
                frame.image,
                window_w,
                window_h,
                session.markers_on_frame(frame.index),
                pose_frame,
                _hud(
                    cursor,
                    session,
                    _pose_status(pose, pose_crop[0]),
                    mode,
                    jump_text,
                    status,
                    foot_note,
                    unsaved=_unsaved(session, feet),
                ),
                foot_corrections=foot_layer,
                show_raw_pose=pose.enabled and (feet is None or feet.show_raw),
                pose_color=pose_color[0],
            )
            _draw_pose_box(canvas, pose_crop[0], drag, frame.image.shape[1], frame.image.shape[0])
            shown = (canvas.shape[1], canvas.shape[0])
            cv2.imshow(WINDOW, canvas)
            started = True
            delay = 1 if not playing else max(1, int(round(1000 / cursor.metadata.fps)))
            key = cv2.waitKeyEx(delay)
            if key == -1:
                key = -1
            else:
                key = key & 0xFFFFFFFF
            if _playback_should_advance(key, bool(clicks), playing):
                if not cursor.step(1):
                    playing = False
                    status = "End of decoded frames."
                continue
            if clicks:
                playing = False
                if feet is not None and feet.active and mode == "view":
                    click_status = _place_foot_click(clicks, cursor, feet, shown)
                else:
                    click_status = _handle_clicks(clicks, cursor, session, shown, mode)
                if click_status:
                    status = click_status
                if key == -1:
                    continue
            if key == -1:
                continue
            if key != ord(" "):
                playing = False
            if key in (ord("r"), ord("R")):
                roi_mode[0] = not roi_mode[0]
                drag["start"] = None
                drag["end"] = None
                status = (
                    "Drag a box around the bowler. This does not follow them."
                    if roi_mode[0]
                    else "Pose-box selection cancelled."
                )
                continue
            if key in (ord("u"), ord("U")):
                pose_crop[0] = None
                status = "Pose box cleared. Dots use the full frame."
                continue
            if key in (ord("p"), ord("P")) and mode == "view":
                pose_color[0] = next_pose_color(pose_color[0])
                status = (
                    f"Pose dot color: {pose_color[0].replace('_', ' ')}. "
                    "Color does not move the landmark or change its accuracy."
                )
                continue
            if feet is not None and mode == "view" and key in (ord("f"), ord("F")):
                name = feet.cycle(1)
                status = (
                    f"Correct {FOOT_LABELS[name]} ({name}). "
                    "This is the athlete's side, not the left or right of the picture. "
                    "Click only if that point is visible."
                )
                continue
            if feet is not None and feet.active and mode == "view" and key == ord("["):
                status = f"Correct {FOOT_LABELS[feet.cycle(-1)]}."
                continue
            if feet is not None and feet.active and mode == "view" and key == ord("]"):
                status = f"Correct {FOOT_LABELS[feet.cycle(1)]}."
                continue
            if feet is not None and feet.active and mode == "view" and key in (ord("x"), ord("X")):
                if feet.clear_selected(frame.index):
                    status = (
                        f"Removed the correction for {feet.selected()} on frame {frame.index}. "
                        "The raw prediction is unchanged."
                    )
                else:
                    status = "No manual correction on this frame for that landmark."
                continue
            if feet is not None and mode == "view" and key in (ord("k"), ord("K")):
                feet.show_raw, feet.show_corrected = _cycle_foot_view(feet.show_raw, feet.show_corrected)
                status = (
                    f"Raw pose dots {'shown' if feet.show_raw else 'hidden'}; "
                    f"manual foot corrections {'shown' if feet.show_corrected else 'hidden'}."
                )
                continue
            if roi_done[0]:
                roi_done[0] = False
                roi_mode[0] = False
                status = _store_pose_box(drag, frame, shown, pose_crop)
                drag["start"] = None
                drag["end"] = None
            mode, jump_text, status, playing = _handle_key(
                key,
                mode,
                jump_text,
                status,
                playing,
                cursor,
                session,
                pose,
                labels_path,
                markers_path,
                video_filename,
                accepted,
                feet,
                foot_path,
            )
            if mode == "quit":
                break
    finally:
        pose.close()


def _playback_should_advance(key: int, pending_clicks: bool, playing: bool) -> bool:
    """Advance playback only when no click is waiting.

    A click is stored on the frame that is on screen. Playback must not move
    to the next frame before that click is applied.
    """
    return key == -1 and playing and not pending_clicks


def _handle_key(
    key: int,
    mode: str,
    jump_text: str,
    status: str,
    playing: bool,
    cursor: FrameCursor,
    session: DeliveryAnnotation,
    pose: "_PoseToggle",
    labels_path: Path,
    markers_path: Path,
    video_filename: str = "",
    accepted: list[bool] | None = None,
    feet: FootReview | None = None,
    foot_path: Path | None = None,
) -> tuple[str, str, str, bool]:
    if accepted is None:
        accepted = [True]
    if mode == "jump":
        return _handle_jump_key(key, jump_text, cursor, status, playing)
    if mode == "confirm_save":
        if key in (ord("y"), ord("Y")):
            if not accepted[0]:
                return (
                    "view",
                    "",
                    "Not saved. Press L before replacing labels that belong to another video.",
                    False,
                )
            try:
                save_delivery(session, labels_path, markers_path, video_filename or None)
                if feet is not None and foot_path is not None:
                    try:
                        replace_delivery_foot_corrections(
                            foot_path,
                            feet.video_sha256,
                            feet.bowler_id,
                            feet.delivery_id,
                            list(feet.items.values()),
                        )
                    except (FootCorrectionError, OSError) as error:
                        session.dirty = True
                        return (
                            "view",
                            "",
                            "Phase frames and marker clicks were written, but foot corrections "
                            f"were not. This delivery is still unsaved. {error}",
                            False,
                        )
                    feet.dirty = False
                status = "Saved phase frames, marker clicks, and any foot corrections."
            except (AnnotationError, OSError) as error:
                status = str(error)
            return "view", "", status, False
        if key in (ord("n"), ord("N"), 27):
            return "view", "", "Save cancelled.", False
        return mode, jump_text, status, False
    if mode == "confirm_quit":
        if key in (ord("y"), ord("Y")):
            print("Quit without saving.")
            return "quit", "", status, False
        if key in (ord("n"), ord("N"), 27):
            return "view", "", "Still unsaved.", False
        return mode, jump_text, status, False

    if key in (ord("q"), ord("Q"), 27):
        if _unsaved(session, feet):
            return "confirm_quit", "", status, False
        return "quit", "", status, False
    if key in _RIGHT_KEYS:
        status = "" if cursor.step(1) else "Already at the last decoded frame."
        return mode, jump_text, status, False
    if key in _LEFT_KEYS:
        status = "" if cursor.step(-1) else "Already at the first frame."
        return mode, jump_text, status, False
    if key == ord(" "):
        return mode, jump_text, status, not playing
    if key == ord("1"):
        session.arm("bfc")
        return mode, jump_text, "BFC selected. Click the back-foot contact point.", False
    if key == ord("2"):
        session.arm("ffc")
        return mode, jump_text, "FFC selected. Click the front-foot contact point.", False
    if key == ord("3"):
        session.arm("release")
        return mode, jump_text, "Release selected. Click the ball-release point.", False
    if key in (ord("c"), ord("C")):
        if session.armed_event is None:
            return mode, jump_text, "Select an event before clearing it.", False
        session.clear(session.armed_event)
        return mode, jump_text, f"Cleared {EVENT_LABELS[session.armed_event]}.", False
    if key in (ord("t"), ord("T")):
        return mode, jump_text, pose.toggle(), False
    if key in (ord("g"), ord("G")):
        return "jump", "", "Type a zero-based frame, then Enter.", False
    if key in (ord("l"), ord("L")) and not accepted[0]:
        load_delivery(session, labels_path, markers_path)
        accepted[0] = True
        return mode, jump_text, "Loaded the labels that were saved for another video.", False
    if key in (ord("s"), ord("S")):
        return "confirm_save", "", status, False
    return mode, jump_text, status, playing


def _handle_jump_key(
    key: int,
    jump_text: str,
    cursor: FrameCursor,
    status: str,
    playing: bool,
) -> tuple[str, str, str, bool]:
    if key in (27,):
        return "view", "", "Jump cancelled.", False
    if key in (8, 127):
        return "jump", jump_text[:-1], status, False
    if key in (13, 10):
        if not jump_text:
            return "view", "", "Jump cancelled.", False
        try:
            cursor.goto(int(jump_text))
        except VideoReadError as error:
            return "view", "", str(error), False
        return "view", "", f"Frame {cursor.index}.", False
    if 0 <= key < 256 and chr(key).isdecimal():
        return "jump", jump_text + chr(key), status, False
    return "jump", jump_text, status, playing


def _pose_status(pose: _PoseToggle, crop: PixelCrop | None) -> str:
    if not pose.enabled:
        return pose.message
    if crop is None:
        return pose.message
    return pose.message + "; limited to your box"


def _store_pose_box(
    drag: dict[str, tuple[int, int] | None],
    frame: VideoFrame,
    shown: tuple[int, int],
    pose_crop: list[PixelCrop | None],
) -> str:
    start = drag.get("start")
    end = drag.get("end")
    if start is None or end is None:
        return "Pose box was not completed."
    box = letterbox_for(frame.image.shape[1], frame.image.shape[0], shown[0], shown[1])
    first = canvas_point_to_normalized(start[0], start[1], box)
    second = canvas_point_to_normalized(end[0], end[1], box)
    if first is None or second is None:
        return "Pose box ignored: keep the drag inside the video."
    try:
        pose_crop[0] = pixel_crop(
            int(round(first[0] * frame.image.shape[1])),
            int(round(first[1] * frame.image.shape[0])),
            int(round(second[0] * frame.image.shape[1])),
            int(round(second[1] * frame.image.shape[0])),
            frame.image.shape[1],
            frame.image.shape[0],
        )
    except PoseCropError as error:
        return str(error)
    return "Pose dots now use that box only. They can still be wrong. Press U to clear it."


def _draw_pose_box(
    canvas: np.ndarray,
    crop: PixelCrop | None,
    drag: dict[str, tuple[int, int] | None],
    image_width: int,
    image_height: int,
) -> None:
    if crop is not None:
        _rectangle_from_image(canvas, crop.x0, crop.y0, crop.x1, crop.y1, image_width, image_height)
    start = drag.get("start")
    end = drag.get("end")
    if start is not None and end is not None:
        cv2.rectangle(canvas, start, end, (0, 128, 255), 1)


def _rectangle_from_image(
    canvas: np.ndarray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    image_width: int,
    image_height: int,
) -> None:
    box = letterbox_for(image_width, image_height, canvas.shape[1], canvas.shape[0])

    def point(x_pixel: int, y_pixel: int) -> tuple[int, int]:
        return (
            int(round(box.pad_x + (x_pixel / image_width) * box.content_width)),
            int(round(box.pad_y + (y_pixel / image_height) * box.content_height)),
        )

    cv2.rectangle(canvas, point(x0, y0), point(x1, y1), (0, 128, 255), 1)


def _place_foot_click(
    clicks: list[tuple[int, int]],
    cursor: FrameCursor,
    feet: FootReview,
    shown: tuple[int, int],
) -> str:
    frame = cursor.current()
    box = letterbox_for(frame.image.shape[1], frame.image.shape[0], shown[0], shown[1])
    status = ""
    while clicks:
        click_x, click_y = clicks.pop(0)
        mapped = canvas_point_to_normalized(click_x, click_y, box)
        if mapped is None:
            status = "Click ignored: it was outside the video frame."
            continue
        try:
            item = feet.place(frame.index, mapped[0], mapped[1])
        except FootCorrectionError as error:
            status = str(error)
            continue
        status = (
            f"Manual correction for {item.landmark_name} on frame {frame.index}. "
            "The raw prediction is unchanged."
        )
    return status


def _cycle_foot_view(show_raw: bool, show_corrected: bool) -> tuple[bool, bool]:
    if show_raw and show_corrected:
        return True, False
    if show_raw and not show_corrected:
        return False, True
    return True, True


def _handle_clicks(
    clicks: list[tuple[int, int]],
    cursor: FrameCursor,
    session: DeliveryAnnotation,
    shown: tuple[int, int],
    mode: str,
) -> str:
    if mode != "view":
        clicks.clear()
        return ""
    frame = cursor.current()
    box = letterbox_for(frame.image.shape[1], frame.image.shape[0], shown[0], shown[1])
    status = ""
    while clicks:
        click_x, click_y = clicks.pop(0)
        mapped = canvas_point_to_normalized(click_x, click_y, box)
        if mapped is None:
            status = "Click ignored: it was outside the video frame."
            continue
        try:
            session.place(frame.index, mapped[0], mapped[1])
            status = f"Marked {EVENT_LABELS[session.armed_event or '']} on frame {frame.index}."
        except AnnotationError as error:
            status = str(error)
    return status


class _PoseToggle:
    """Optional image-mode pose dots. Manual marks do not depend on this."""

    def __init__(self) -> None:
        self.enabled = False
        self.message = "pose off"
        self._landmarker: object | None = None

    def toggle(self) -> str:
        self.enabled = not self.enabled
        if not self.enabled:
            self.message = "pose off"
            return self.message
        if self._landmarker is None:
            try:
                self._landmarker = _create_image_landmarker()
            except (AnnotationError, OSError, ValueError, RuntimeError) as error:
                self.enabled = False
                self.message = str(error)
                return self.message
            self.message = "unverified pose dots; may be another person; not an event"
        return self.message

    def estimate(self, frame: VideoFrame, crop: PixelCrop | None = None) -> object | None:
        if not self.enabled or self._landmarker is None:
            return None
        try:
            import mediapipe as mp

            from app.pose.mediapipe_estimator import pose_frame_from_result

            image = frame.image
            if crop is not None:
                image = np.ascontiguousarray(frame.image[crop.y0 : crop.y1, crop.x0 : crop.x1])
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            result = self._landmarker.detect(mp_image)  # type: ignore[attr-defined]
            pose = pose_frame_from_result(
                result,
                VideoFrame(index=frame.index, timestamp_seconds=frame.timestamp_seconds, image=image),
            )
            if crop is None:
                return pose
            return remap_pose_to_full_frame(pose, crop, frame.image.shape[1], frame.image.shape[0])
        except (ValueError, RuntimeError, OSError):
            self.message = "pose failed on this frame; manual marking still works"
            return None

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()  # type: ignore[attr-defined]
            self._landmarker = None


def _create_image_landmarker() -> object:
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

    from app.pose.mediapipe_estimator import DEFAULT_MODEL_PATH

    model_path = Path(DEFAULT_MODEL_PATH)
    if not model_path.is_file():
        raise AnnotationError(f"Pose model file {model_path.name} was not found. Overlay stays off.")
    options = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=RunningMode.IMAGE,
        num_poses=1,
    )
    try:
        return PoseLandmarker.create_from_options(options)
    except (ValueError, RuntimeError) as error:
        raise AnnotationError(f"Pose overlay could not start: {error}") from error


def _unsaved(session: DeliveryAnnotation, feet: FootReview | None) -> bool:
    """True when phase labels or manual foot corrections still need a confirmed save."""
    return session.dirty or (feet is not None and feet.dirty)


def _hud(
    cursor: FrameCursor,
    session: DeliveryAnnotation,
    pose_message: str,
    mode: str,
    jump_text: str,
    status: str,
    foot_note: str = "",
    unsaved: bool = False,
) -> list[str]:
    timestamp = cursor.timestamp_seconds
    timestamp_text = "—" if timestamp is None else f"{timestamp:.3f}s encoded fps"
    header = cursor.metadata.frame_count
    if cursor.decoded_count is None:
        count_text = f"header {header}; full decoded length not read"
    elif cursor.decoded_count != header:
        count_text = f"decoded {cursor.decoded_count}; header {header}"
    else:
        count_text = f"{header} frames"
    lines = [
        f"frame {cursor.index}  {timestamp_text}  {count_text}",
        (
            f"BFC {_frame_text(session.bfc_frame)}  "
            f"FFC {_frame_text(session.ffc_frame)}  "
            f"REL {_frame_text(session.release_frame)}"
        ),
        f"armed {EVENT_LABELS.get(session.armed_event or '', 'none')}  {pose_message}  "
        f"{'unsaved' if unsaved or session.dirty else 'no unsaved edits'}",
        HELP,
    ]
    if foot_note:
        lines.append(foot_note)
    if mode == "jump":
        lines.append(f"jump: {jump_text}")
    elif mode == "confirm_save":
        lines.append(f"Save manual labels for {session.bowler_id}/{session.delivery_id}? y/n")
    elif mode == "confirm_quit":
        lines.append("Quit and discard unsaved edits? y/n")
    if status:
        lines.append(status)
    return lines


def _frame_text(frame_index: int | None) -> str:
    return "—" if frame_index is None else str(frame_index)


def _initial_window_size(image_width: int, image_height: int) -> tuple[int, int]:
    longest = max(image_width, image_height, 1)
    scale = 1.0 if longest <= 960 else 960 / longest
    return max(320, int(round(image_width * scale))), max(240, int(round(image_height * scale)))


if __name__ == "__main__":
    raise SystemExit(main())
