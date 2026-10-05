"""Tests for the OpenCV video reader.

Test videos are generated into pytest's temporary directory and never committed.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.video import (
    VideoMetadata,
    VideoReadError,
    iter_frames,
    read_video_metadata,
)

WIDTH = 64
HEIGHT = 48
FPS = 10.0
FRAME_COUNT = 15
# Lossy codecs shift flat colours slightly; this is far smaller than the
# brightness step between consecutive test frames.
BRIGHTNESS_TOLERANCE = 4


def frame_brightness(index: int) -> int:
    return index * 15


@pytest.fixture(
    params=[("avi", "MJPG"), ("mp4", "mp4v"), ("mov", "mp4v")],
    ids=["avi-mjpg", "mp4-mp4v", "mov-mp4v"],
)
def test_video(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    extension, codec = request.param
    path = tmp_path / f"test.{extension}"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*codec), FPS, (WIDTH, HEIGHT)
    )
    if not writer.isOpened():
        pytest.skip(f"This OpenCV build cannot write {codec} into .{extension}")
    for index in range(FRAME_COUNT):
        writer.write(np.full((HEIGHT, WIDTH, 3), frame_brightness(index), np.uint8))
    writer.release()
    return path


class FakeCapture:
    """Stands in for cv2.VideoCapture to simulate broken videos."""

    def __init__(
        self,
        properties: dict[int, float],
        can_read: bool,
        max_frames: int | None = None,
    ) -> None:
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


def fake_properties(
    fps: float = FPS,
    width: float = float(WIDTH),
    height: float = float(HEIGHT),
    frame_count: float = float(FRAME_COUNT),
) -> dict[int, float]:
    return {
        cv2.CAP_PROP_FRAME_WIDTH: width,
        cv2.CAP_PROP_FRAME_HEIGHT: height,
        cv2.CAP_PROP_FPS: fps,
        cv2.CAP_PROP_FRAME_COUNT: frame_count,
    }


@pytest.fixture
def existing_file(tmp_path: Path) -> Path:
    path = tmp_path / "fake.mp4"
    path.write_bytes(b"")
    return path


def use_fake_capture(monkeypatch: pytest.MonkeyPatch, capture: FakeCapture) -> None:
    monkeypatch.setattr(cv2, "VideoCapture", lambda *args: capture)


def test_valid_video_metadata(test_video: Path) -> None:
    metadata = read_video_metadata(test_video)

    assert isinstance(metadata, VideoMetadata)
    assert metadata.width == WIDTH
    assert metadata.height == HEIGHT
    assert metadata.fps == pytest.approx(FPS)
    assert metadata.frame_count == FRAME_COUNT


def test_duration_is_frame_count_over_fps(test_video: Path) -> None:
    metadata = read_video_metadata(test_video)

    assert metadata.duration_seconds == pytest.approx(FRAME_COUNT / FPS)


def test_duration_calculation() -> None:
    metadata = VideoMetadata(width=1920, height=1080, fps=30.0, frame_count=90)

    assert metadata.duration_seconds == pytest.approx(3.0)


def test_duration_with_ntsc_fps() -> None:
    fps = 30000 / 1001
    metadata = VideoMetadata(width=1920, height=1080, fps=fps, frame_count=684)

    assert metadata.duration_seconds == pytest.approx(684 / fps)
    assert metadata.duration_seconds == pytest.approx(22.822822822822823)


def test_iterates_all_frames_in_order(test_video: Path) -> None:
    frames = list(iter_frames(test_video))

    assert len(frames) == FRAME_COUNT
    assert [frame.index for frame in frames] == list(range(FRAME_COUNT))
    for frame in frames:
        assert frame.image.shape == (HEIGHT, WIDTH, 3)
        assert frame.image.dtype == np.uint8
        assert abs(frame.image.mean() - frame_brightness(frame.index)) <= BRIGHTNESS_TOLERANCE


def test_frame_timestamps(test_video: Path) -> None:
    frames = list(iter_frames(test_video))
    duration = read_video_metadata(test_video).duration_seconds

    assert frames[0].timestamp_seconds == 0.0
    for frame in frames:
        assert frame.timestamp_seconds == pytest.approx(frame.index / FPS)
        assert 0.0 <= frame.timestamp_seconds < duration


READERS = pytest.mark.parametrize(
    "read",
    [read_video_metadata, lambda path: list(iter_frames(path))],
    ids=["metadata", "frames"],
)


@READERS
def test_missing_file(tmp_path: Path, read) -> None:
    with pytest.raises(FileNotFoundError, match="Video file not found"):
        read(tmp_path / "does_not_exist.mp4")


@pytest.mark.parametrize("contents", [b"", b"this is not a video" * 100], ids=["empty", "garbage"])
@READERS
def test_invalid_video(tmp_path: Path, contents: bytes, read) -> None:
    path = tmp_path / "broken.mp4"
    path.write_bytes(contents)

    with pytest.raises(VideoReadError, match="could not open"):
        read(path)


@pytest.mark.parametrize("fps", [0.0, -1.0, float("nan")])
def test_invalid_fps_is_rejected(
    monkeypatch: pytest.MonkeyPatch, existing_file: Path, fps: float
) -> None:
    capture = FakeCapture(fake_properties(fps=fps), can_read=True)
    use_fake_capture(monkeypatch, capture)

    with pytest.raises(VideoReadError, match="invalid FPS"):
        read_video_metadata(existing_file)
    assert capture.released


def test_undecodable_first_frame_is_rejected(
    monkeypatch: pytest.MonkeyPatch, existing_file: Path
) -> None:
    capture = FakeCapture(fake_properties(), can_read=False)
    use_fake_capture(monkeypatch, capture)

    with pytest.raises(VideoReadError, match="could not decode its first frame"):
        read_video_metadata(existing_file)
    assert capture.released


def test_iterating_undecodable_video_is_rejected(
    monkeypatch: pytest.MonkeyPatch, existing_file: Path
) -> None:
    capture = FakeCapture(fake_properties(), can_read=False)
    use_fake_capture(monkeypatch, capture)

    with pytest.raises(VideoReadError, match="could not decode any frames"):
        list(iter_frames(existing_file))
    assert capture.released


@pytest.mark.parametrize(
    ("width", "height"),
    [(0.0, float(HEIGHT)), (float(WIDTH), 0.0), (-8.0, float(HEIGHT)), (float("nan"), float(HEIGHT))],
    ids=["zero-width", "zero-height", "negative-width", "nan-width"],
)
def test_invalid_frame_size_is_rejected(
    monkeypatch: pytest.MonkeyPatch, existing_file: Path, width: float, height: float
) -> None:
    capture = FakeCapture(fake_properties(width=width, height=height), can_read=True)
    use_fake_capture(monkeypatch, capture)

    with pytest.raises(VideoReadError, match="invalid frame size"):
        read_video_metadata(existing_file)
    assert capture.released


@pytest.mark.parametrize("frame_count", [0.0, -3.0, float("nan")])
def test_invalid_frame_count_is_rejected(
    monkeypatch: pytest.MonkeyPatch, existing_file: Path, frame_count: float
) -> None:
    capture = FakeCapture(fake_properties(frame_count=frame_count), can_read=True)
    use_fake_capture(monkeypatch, capture)

    with pytest.raises(VideoReadError, match="invalid frame count"):
        read_video_metadata(existing_file)
    assert capture.released


def test_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(VideoReadError, match="is not a file"):
        read_video_metadata(tmp_path)


def test_unusual_but_valid_fps(monkeypatch: pytest.MonkeyPatch, existing_file: Path) -> None:
    capture = FakeCapture(fake_properties(fps=240.0), can_read=True)
    use_fake_capture(monkeypatch, capture)

    metadata = read_video_metadata(existing_file)

    assert metadata.fps == pytest.approx(240.0)
    assert metadata.duration_seconds == pytest.approx(FRAME_COUNT / 240.0)
    assert capture.released


def test_iter_frames_releases_when_closed_early(
    monkeypatch: pytest.MonkeyPatch, existing_file: Path
) -> None:
    capture = FakeCapture(fake_properties(), can_read=True, max_frames=10)
    use_fake_capture(monkeypatch, capture)

    frames = iter_frames(existing_file)
    first = next(frames)
    frames.close()

    assert first.index == 0
    assert capture.released


def test_decoded_frame_count_can_differ_from_header(
    monkeypatch: pytest.MonkeyPatch, existing_file: Path
) -> None:
    capture = FakeCapture(fake_properties(frame_count=15), can_read=True, max_frames=4)
    use_fake_capture(monkeypatch, capture)

    frames = list(iter_frames(existing_file))

    assert [frame.index for frame in frames] == [0, 1, 2, 3]
    assert frames[-1].timestamp_seconds == pytest.approx(3 / FPS)
    assert capture.released
