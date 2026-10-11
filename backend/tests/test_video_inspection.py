"""Tests for read-only video inspection. Clips are temporary synthetic files."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.video.inspect import format_inspection, inspect_video, main

WIDTH = 64
HEIGHT = 48
FPS = 10.0
FRAMES = 6


def _write_clip(path: Path, width: int, height: int, count: int = FRAMES) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (width, height))
    if not writer.isOpened():
        pytest.skip("This OpenCV build cannot write an MJPG test clip.")
    for index in range(count):
        writer.write(np.full((height, width, 3), index * 20, np.uint8))
    writer.release()


class _FakeCapture:
    def __init__(self, properties: dict[int, float], *, can_read: bool = True, max_frames: int | None = None) -> None:
        self.properties = properties
        self.can_read = can_read
        self.max_frames = max_frames
        self.reads = 0
        self.released = False

    def isOpened(self) -> bool:
        return True

    def get(self, prop: int) -> float:
        return self.properties.get(prop, 0.0)

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self.can_read:
            return False, None
        if self.max_frames is not None and self.reads >= self.max_frames:
            return False, None
        self.reads += 1
        return True, np.zeros((HEIGHT, WIDTH, 3), np.uint8)

    def release(self) -> None:
        self.released = True


def _properties(
    *,
    width: float = float(WIDTH),
    height: float = float(HEIGHT),
    fps: float = FPS,
    frame_count: float = float(FRAMES),
) -> dict[int, float]:
    return {
        cv2.CAP_PROP_FRAME_WIDTH: width,
        cv2.CAP_PROP_FRAME_HEIGHT: height,
        cv2.CAP_PROP_FPS: fps,
        cv2.CAP_PROP_FRAME_COUNT: frame_count,
    }


def _use_fresh(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> list[_FakeCapture]:
    opened: list[_FakeCapture] = []

    def factory(*_args: object) -> _FakeCapture:
        capture = _FakeCapture(_properties(**kwargs))  # type: ignore[arg-type]
        opened.append(capture)
        return capture

    monkeypatch.setattr(cv2, "VideoCapture", factory)
    return opened


def test_landscape_and_portrait_clips_are_described(tmp_path: Path) -> None:
    landscape = tmp_path / "wide.avi"
    portrait = tmp_path / "tall.avi"
    _write_clip(landscape, WIDTH, HEIGHT)
    _write_clip(portrait, HEIGHT, WIDTH)
    wide = inspect_video(landscape)
    tall = inspect_video(portrait)
    assert wide.orientation == "landscape"
    assert wide.width == WIDTH and wide.height == HEIGHT
    assert wide.encoded_fps == pytest.approx(FPS)
    assert wide.first_frame_decoded is True
    assert wide.final_portion_decoded is True
    assert wide.decoded_frame_count == wide.reported_frame_count
    assert wide.error is None
    assert "capture clock" in " ".join(wide.warnings)
    assert "suitable" in " ".join(wide.warnings)
    assert tall.orientation == "portrait"
    assert tall.width == HEIGHT and tall.height == WIDTH
    text = format_inspection(wide)
    assert "filename: wide.avi" in text
    assert "error: unavailable" in text


def test_missing_file_is_reported_without_invented_metadata(tmp_path: Path) -> None:
    report = inspect_video(tmp_path / "missing.mp4")
    assert report.error is not None
    assert "not found" in report.error
    assert report.width is None
    assert report.encoded_fps is None
    assert report.reported_frame_count is None
    assert report.first_frame_decoded is False
    assert "missing.mp4" in report.filename
    assert str(tmp_path) not in (report.error or "")


def test_invalid_fps_and_dimensions_are_not_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"not-empty")
    opened = _use_fresh(monkeypatch, fps=0.0)
    fps_report = inspect_video(path)
    assert fps_report.error is not None
    assert "FPS" in fps_report.error
    assert fps_report.encoded_fps is None
    assert opened[0].released

    opened = _use_fresh(monkeypatch, width=0.0)
    size_report = inspect_video(path)
    assert size_report.error is not None
    assert "frame size" in size_report.error
    assert size_report.width is None
    assert opened[0].released


def test_decoder_failure_and_short_decode_are_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "short.mp4"
    path.write_bytes(b"not-empty")

    def fail_open(*_args: object) -> _FakeCapture:
        capture = _FakeCapture(_properties(), can_read=False)
        fail_open.opened.append(capture)  # type: ignore[attr-defined]
        return capture

    fail_open.opened = []  # type: ignore[attr-defined]
    monkeypatch.setattr(cv2, "VideoCapture", fail_open)
    failed = inspect_video(path)
    assert failed.first_frame_decoded is False
    assert failed.decode_end_status == "unavailable"
    assert failed.final_portion_decoded is None
    assert "decode" in (failed.error or "")
    assert fail_open.opened[0].released  # type: ignore[attr-defined]

    def short_open(*_args: object) -> _FakeCapture:
        capture = _FakeCapture(_properties(frame_count=6), max_frames=2)
        short_open.opened.append(capture)  # type: ignore[attr-defined]
        return capture

    short_open.opened = []  # type: ignore[attr-defined]
    monkeypatch.setattr(cv2, "VideoCapture", short_open)
    short = inspect_video(path)
    assert short.first_frame_decoded is True
    assert short.reported_frame_count == 6
    assert short.decoded_frame_count == 2
    assert short.decode_end_status == "header_count_disagreement"
    assert short.final_portion_decoded is None
    assert "6 frames but 2" in " ".join(short.warnings)
    assert "final portion" not in " ".join(short.warnings).lower()
    assert all(capture.released for capture in short_open.opened)  # type: ignore[attr-defined]


def test_a_decode_exception_is_not_described_as_a_header_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "clip.avi"
    _write_clip(path, WIDTH, HEIGHT)

    def fail_iteration(_path: Path):
        raise cv2.error("decode broke")

    monkeypatch.setattr("app.video.inspect.iter_frames", fail_iteration)
    report = inspect_video(path)
    assert report.decode_end_status == "premature_decode_error"
    assert report.final_portion_decoded is False
    assert report.decoded_frame_count == 0
    assert report.error is not None
    assert "decode broke" in report.error


def test_inspection_does_not_modify_the_file(tmp_path: Path) -> None:
    path = tmp_path / "kept.avi"
    _write_clip(path, WIDTH, HEIGHT)
    before = path.read_bytes()
    report = inspect_video(path)
    assert report.error is None
    assert path.read_bytes() == before


def test_cli_prints_the_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "clip.avi"
    _write_clip(path, WIDTH, HEIGHT)
    assert main([str(path)]) == 0
    output = capsys.readouterr().out
    assert "filename: clip.avi" in output
    assert "orientation: landscape" in output
    assert main([str(tmp_path / "nope.mp4")]) == 1
