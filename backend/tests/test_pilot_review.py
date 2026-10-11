"""Synthetic checks for the pilot pose review command. Not bowling validation."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.pose.estimator import PoseEstimationError
from app.pose.landmarks import Landmark, PoseFrame
from app.quality.pilot_review import PilotReviewError, run_pilot_review
from app.video import VideoFrame

WIDTH = 32
HEIGHT = 24
FPS = 10.0
COUNT = 4


def _write_clip(path: Path, count: int = COUNT) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        pytest.skip("This OpenCV build cannot write an MJPG test clip.")
    for index in range(count):
        writer.write(np.full((HEIGHT, WIDTH, 3), 20 + index * 30, np.uint8))
    writer.release()


class _ScriptedEstimator:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.closed = False
        self.seen: list[int] = []
        self.last_pose: PoseFrame | None = None

    def estimate(self, frame: VideoFrame) -> PoseFrame:
        self.seen.append(frame.index)
        if self.mode == "fail" and frame.index == 1:
            raise PoseEstimationError("pose stopped")
        detected = self.mode in {"all", "partial"} or (self.mode == "even" and frame.index % 2 == 0)
        landmarks = {}
        if detected and self.mode != "partial":
            landmarks = {
                "nose": Landmark("nose", 0.5, 0.2, 0.9, 0.8),
                "left_ankle": Landmark("left_ankle", 0.4, 0.8, 0.5, 0.4),
            }
        elif detected:
            landmarks = {"nose": Landmark("nose", 0.5, 0.2, None, None)}
        pose = PoseFrame(
            frame_index=frame.index,
            timestamp_seconds=frame.timestamp_seconds,
            image_width=frame.image.shape[1],
            image_height=frame.image.shape[0],
            landmarks=landmarks,
        )
        self.last_pose = pose
        return pose

    def close(self) -> None:
        self.closed = True


def test_short_video_reports_full_pose_without_a_grade(tmp_path: Path) -> None:
    video = tmp_path / "clip.avi"
    output = tmp_path / "out"
    _write_clip(video)
    before = video.read_bytes()
    estimator = _ScriptedEstimator("all")
    result = run_pilot_review(video, output, estimator=estimator)
    text = result.report_path.read_text(encoding="utf-8") if result.report_path else ""
    assert result.error is None
    assert estimator.closed is True
    assert estimator.seen == list(range(COUNT))
    assert "pose_detection_percent: 100.00" in text
    assert "missing_pose_count: 0" in text
    assert "Not bowler identity" in text
    assert "jitter grade" in text
    assert "good" not in text.lower()
    assert video.read_bytes() == before
    assert {path.suffix for path in output.iterdir()} == {".txt"}


def test_missing_and_corrupt_videos_do_not_start_pose(tmp_path: Path) -> None:
    output = tmp_path / "out"
    estimator = _ScriptedEstimator("all")
    missing = run_pilot_review(tmp_path / "missing.mp4", output, estimator=estimator)
    assert missing.error is not None
    assert "not found" in missing.error
    assert estimator.closed is False
    assert estimator.seen == []

    corrupt = tmp_path / "broken.mp4"
    corrupt.write_bytes(b"this is not a video")
    failed = run_pilot_review(corrupt, output, estimator=estimator)
    assert failed.error is not None
    assert estimator.seen == []
    assert "caveats:" in (failed.report_path.read_text(encoding="utf-8") if failed.report_path else "")


def test_absent_intermittent_and_partial_pose(tmp_path: Path) -> None:
    video = tmp_path / "clip.avi"
    _write_clip(video)
    none = run_pilot_review(video, tmp_path / "none", estimator=_ScriptedEstimator("none"))
    none_text = none.report_path.read_text(encoding="utf-8")
    assert "pose_detection_percent: 0.00" in none_text
    assert "missing_pose_count: 4" in none_text
    assert "longest_missing_pose_run_frames: 4" in none_text

    even = run_pilot_review(video, tmp_path / "even", estimator=_ScriptedEstimator("even"))
    even_text = even.report_path.read_text(encoding="utf-8")
    assert "pose_detection_percent: 50.00" in even_text

    partial = run_pilot_review(video, tmp_path / "partial", estimator=_ScriptedEstimator("partial"))
    partial_text = partial.report_path.read_text(encoding="utf-8")
    assert "left_ankle: frames_with_landmark=0" in partial_text
    assert "nose: frames_with_landmark=4" in partial_text


def test_review_frame_uses_the_same_index_and_rejects_bounds(tmp_path: Path) -> None:
    video = tmp_path / "clip.avi"
    output = tmp_path / "frames"
    _write_clip(video)
    result = run_pilot_review(video, output, review_frames=(1, 99, -1), estimator=_ScriptedEstimator("all"))
    text = result.report_path.read_text(encoding="utf-8")
    image = cv2.imread(str(output / "frame_1.png"))
    assert image is not None
    assert image.shape[0] == HEIGHT and image.shape[1] == WIDTH
    assert "frame_1.png" in text
    assert "outside decoded frames" in text
    assert "not a valid index" in text
    assert not (output / "frame_99.png").exists()
    assert not any(path.suffix == ".csv" for path in output.iterdir())


    assert not any(path.suffix == ".csv" for path in output.iterdir())


def test_duplicate_review_frame_is_named_and_pose_coordinates_stay_put(tmp_path: Path) -> None:
    video = tmp_path / "clip.avi"
    output = tmp_path / "frames"
    _write_clip(video)
    estimator = _ScriptedEstimator("all")
    result = run_pilot_review(video, output, review_frames=(1, 1), estimator=estimator)
    text = result.report_path.read_text(encoding="utf-8")
    assert "requested more than once" in text
    assert list(output.glob("frame_1.png"))
    pose = estimator.last_pose
    assert pose is not None
    assert pose.landmarks["left_ankle"].x == pytest.approx(0.4)
    assert pose.landmarks["left_ankle"].y == pytest.approx(0.8)


def test_frame_export_failure_is_reported_and_is_not_a_successful_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = tmp_path / "clip.avi"
    output = tmp_path / "frames"
    _write_clip(video)
    monkeypatch.setattr(cv2, "imwrite", lambda *_args, **_kwargs: False)
    result = run_pilot_review(video, output, review_frames=(1,), estimator=_ScriptedEstimator("all"))
    text = result.report_path.read_text(encoding="utf-8") if result.report_path else ""
    assert result.error is not None
    assert "Could not write" in result.error
    assert "export_error:" in text
    assert "pose_detection_percent:" in text
    assert "Analysis of decoded frames was summarised. Frame export did not finish." in text


def test_output_path_must_be_a_directory_and_failures_close_the_estimator(tmp_path: Path) -> None:
    video = tmp_path / "clip.avi"
    _write_clip(video)
    blocked = tmp_path / "not_a_directory"
    blocked.write_text("reserved", encoding="utf-8")
    with pytest.raises(PilotReviewError, match="not a directory"):
        run_pilot_review(video, blocked, estimator=_ScriptedEstimator("all"))

    before = video.read_bytes()
    estimator = _ScriptedEstimator("fail")
    result = run_pilot_review(video, tmp_path / "failed", estimator=estimator)
    assert estimator.closed is True
    assert result.error is not None
    assert "pose stopped" in result.error
    assert video.read_bytes() == before
