"""Deployment guards. Synthetic clips only. Demonstration sessions are not opened."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.http_guards import host_allowed
from app.api.pose_review_jobs import get_job_runner, reset_job_runner, set_estimator_factory
from app.api.settings import ApiSettings, ensure_session_storage, load_settings, set_settings_override
from app.main import app
from app.pose.estimator import PoseEstimationError
from app.pose.landmarks import Landmark, PoseFrame
from app.video import VideoFrame
from app.video.inspect import DURATION_LIMIT_ERROR, FRAME_LIMIT_ERROR

WIDTH = 32
HEIGHT = 24


class _Estimator:
    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.closed = False

    def estimate(self, frame: VideoFrame) -> PoseFrame:
        if self.mode == "fail":
            raise PoseEstimationError("pose stopped")
        return PoseFrame(
            frame_index=frame.index,
            timestamp_seconds=frame.timestamp_seconds,
            image_width=frame.image.shape[1],
            image_height=frame.image.shape[0],
            landmarks={"nose": Landmark("nose", 0.5, 0.2, 0.9, 0.8)},
        )

    def close(self) -> None:
        self.closed = True


def _settings(tmp_path: Path, **overrides: object) -> ApiSettings:
    values: dict[str, object] = {
        "session_root": tmp_path / "sessions",
        "max_upload_bytes": 8 * 1024 * 1024,
    }
    values.update(overrides)
    settings = ApiSettings(**values)  # type: ignore[arg-type]
    set_settings_override(settings)
    reset_job_runner()
    return settings


def _clip(path: Path, frames: int, fps: float = 10.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (WIDTH, HEIGHT))
    try:
        if not writer.isOpened():
            pytest.skip("This OpenCV build cannot write an MJPG test clip.")
        for index in range(frames):
            writer.write(np.full((HEIGHT, WIDTH, 3), 20 + (index % 50), np.uint8))
    finally:
        writer.release()


def _upload(client: TestClient, video: Path, delivery: str = "D01"):
    return client.post(
        "/api/sessions",
        data={"bowler_id": "B01", "delivery_id": delivery},
        files={"video": (video.name, video.read_bytes(), "video/x-msvideo")},
    )


@pytest.fixture
def client(tmp_path: Path):
    _settings(tmp_path)
    yield TestClient(app, raise_server_exceptions=False)
    set_settings_override(None)
    reset_job_runner()
    set_estimator_factory(None)


def test_default_limits_accept_a_demonstration_sized_clip(client: TestClient, tmp_path: Path) -> None:
    settings = ApiSettings(session_root=tmp_path, max_upload_bytes=1024)
    assert settings.max_decoded_frames >= 223
    assert settings.max_duration_seconds >= 8
    video = tmp_path / "delivery.avi"
    _clip(video, 223)
    created = _upload(client, video)
    assert created.status_code == 200
    assert created.json()["decoded_frame_count"] == 223
    assert "Users" not in created.text
    assert "\\" not in created.json()["scientific_caveat"]


def test_over_frame_and_over_duration_videos_are_rejected(client: TestClient, tmp_path: Path) -> None:
    video = tmp_path / "clip.avi"
    _clip(video, 4)
    _settings(tmp_path, max_decoded_frames=3, max_duration_seconds=30)
    too_many = _upload(client, video)
    assert too_many.status_code == 400
    assert too_many.json()["detail"] == FRAME_LIMIT_ERROR
    assert not any((tmp_path / "sessions").glob("*"))

    _settings(tmp_path, max_decoded_frames=1800, max_duration_seconds=0.3)
    too_long = _upload(client, video, "D02")
    assert too_long.status_code == 400
    assert too_long.json()["detail"] == DURATION_LIMIT_ERROR
    assert not any((tmp_path / "sessions").glob("*"))


def test_frame_and_duration_boundaries_are_accepted(client: TestClient, tmp_path: Path) -> None:
    video = tmp_path / "edge.avi"
    _clip(video, 4, fps=10.0)
    _settings(tmp_path, max_decoded_frames=4, max_duration_seconds=0.4)
    created = _upload(client, video)
    assert created.status_code == 200
    assert created.json()["decoded_frame_count"] == 4


def test_malformed_video_is_rejected_without_a_session(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/api/sessions",
        data={"bowler_id": "B01", "delivery_id": "D01"},
        files={"video": ("clip.avi", b"this is not a video", "video/x-msvideo")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Video could not be decoded."
    assert "\\" not in response.text
    assert not (tmp_path / "sessions").exists() or not any((tmp_path / "sessions").glob("*"))


def test_path_traversal_session_id_is_rejected(client: TestClient) -> None:
    response = client.get("/api/sessions/..%2F..%2Fsecret")
    assert response.status_code in {400, 404, 422}
    assert response.status_code != 200
    dotted = client.get("/api/sessions/" + ("a" * 31) + "g")
    assert dotted.status_code == 400


def test_upload_rate_limit_and_read_access(client: TestClient, tmp_path: Path) -> None:
    _settings(tmp_path, upload_limit=1, rate_window_seconds=600)
    video = tmp_path / "one.avi"
    _clip(video, 2)
    first = _upload(client, video)
    assert first.status_code == 200
    session_id = first.json()["session_id"]
    second = _upload(client, video, "D02")
    assert second.status_code == 429
    assert "wait" in second.json()["detail"].lower()
    assert client.get(f"/api/sessions/{session_id}").status_code == 200
    assert client.get("/health").status_code == 200


def test_job_rate_limit_still_allows_the_completed_report(client: TestClient, tmp_path: Path) -> None:
    _settings(tmp_path, job_limit=1, rate_window_seconds=600)
    video = tmp_path / "job.avi"
    _clip(video, 3)
    created = _upload(client, video)
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    set_estimator_factory(lambda: _Estimator())
    reset_job_runner()
    started = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [0]})
    assert started.status_code == 202
    assert get_job_runner().wait_until_idle()
    blocked = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [1]})
    assert blocked.status_code == 429
    report = client.get(f"/api/sessions/{session_id}/pose-review/report")
    assert report.status_code == 200
    assert report.json()["overlay_frames"] == [0]


def test_pose_capacity_does_not_block_reading(client: TestClient, tmp_path: Path) -> None:
    _settings(tmp_path, max_pose_jobs=1, job_limit=10)
    video = tmp_path / "cap.avi"
    _clip(video, 2)
    first = _upload(client, video).json()["session_id"]
    second = _upload(client, video, "D02").json()["session_id"]
    gate_started = __import__("threading").Event()
    release = __import__("threading").Event()

    class _Gated(_Estimator):
        def estimate(self, frame: VideoFrame) -> PoseFrame:
            gate_started.set()
            release.wait(timeout=5)
            return super().estimate(frame)

    set_estimator_factory(lambda: _Gated())
    reset_job_runner()
    started = client.post(f"/api/sessions/{first}/pose-review", json={})
    assert started.status_code == 202
    assert gate_started.wait(timeout=5)
    full = client.post(f"/api/sessions/{second}/pose-review", json={})
    assert full.status_code == 503
    assert client.get(f"/api/sessions/{first}").status_code == 200
    release.set()
    assert get_job_runner().wait_until_idle()


def test_failed_pose_rerun_preserves_the_previous_overlay(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    _settings(tmp_path)
    video = tmp_path / "rerun.avi"
    _clip(video, 3)
    session_id = _upload(client, video).json()["session_id"]
    set_estimator_factory(lambda: _Estimator())
    reset_job_runner()
    first = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [0]})
    assert first.status_code == 202
    first_id = first.json()["job_id"]
    assert get_job_runner().wait_until_idle()
    overlay = client.get(f"/api/sessions/{session_id}/pose-review/frames/0")
    assert overlay.status_code == 200
    png = overlay.content
    set_estimator_factory(lambda: _Estimator("fail"))
    reset_job_runner()
    failed = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [1]})
    assert failed.status_code == 202
    assert get_job_runner().wait_until_idle()
    status = client.get(f"/api/sessions/{session_id}/pose-review")
    assert status.json()["status"] == "completed"
    assert status.json()["job_id"] == first_id
    kept = client.get(f"/api/sessions/{session_id}/pose-review/frames/0")
    assert kept.status_code == 200
    assert kept.content == png
    assert client.get(f"/api/sessions/{session_id}/pose-review/frames/1").status_code == 404
    assert (root / session_id / "pose_review" / "report.txt").is_file()

    set_estimator_factory(lambda: _Estimator())
    reset_job_runner()
    again = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [1]})
    assert again.status_code == 202
    assert get_job_runner().wait_until_idle()
    replaced = client.get(f"/api/sessions/{session_id}/pose-review")
    assert replaced.json()["status"] == "completed"
    assert replaced.json()["job_id"] == again.json()["job_id"]
    assert client.get(f"/api/sessions/{session_id}/pose-review/frames/1").status_code == 200
    assert client.get(f"/api/sessions/{session_id}/pose-review/frames/0").status_code == 404


def test_labels_cannot_be_replaced_after_a_measurement_report(client: TestClient, tmp_path: Path) -> None:
    video = tmp_path / "labels.avi"
    _clip(video, 4)
    session_id = _upload(client, video).json()["session_id"]
    body = {
        "bfc_frame": 0,
        "ffc_frame": 1,
        "release_frame": 3,
        "front_leg": "left",
        "confirm_front_leg": True,
        "confirm_label_link": True,
        "labeler": "SS",
        "notes": "",
        "replace_existing": False,
    }
    saved = client.put(f"/api/sessions/{session_id}/labels", json=body)
    assert saved.status_code == 200
    report = tmp_path / "sessions" / session_id / "measurement" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")
    replaced = dict(body)
    replaced["ffc_frame"] = 2
    replaced["replace_existing"] = True
    rejected = client.put(f"/api/sessions/{session_id}/labels", json=replaced)
    assert rejected.status_code == 409
    assert "measurement report" in rejected.json()["detail"]
    current = client.get(f"/api/sessions/{session_id}/labels")
    assert current.json()["ffc_frame"] == 1


def test_storage_root_survives_a_second_startup_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "persist"
    monkeypatch.setenv("FAST_BOWLING_SESSION_ROOT", str(root))
    set_settings_override(None)
    settings = load_settings()
    ensure_session_storage(settings)
    marker = root / "keep.txt"
    marker.write_text("stay", encoding="utf-8")
    ensure_session_storage(settings)
    assert marker.read_text(encoding="utf-8") == "stay"
    assert not (root / ".paceframe-write-probe").exists()


def test_relative_storage_root_is_resolved_from_the_backend_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAST_BOWLING_SESSION_ROOT", "relative-storage-test")
    set_settings_override(None)
    resolved = load_settings().session_root
    assert resolved.is_absolute()
    assert resolved.name == "relative-storage-test"
    assert resolved.parent.name == "backend"
    assert not resolved.exists()


def test_unlisted_host_is_rejected(tmp_path: Path) -> None:
    assert host_allowed("testserver", ("localhost", "127.0.0.1", "testserver", "::1"))
    assert host_allowed("localhost:5173", ("localhost",))
    assert not host_allowed("evil.example", ("localhost", "127.0.0.1"))
    _settings(tmp_path, trusted_hosts=("localhost", "127.0.0.1", "testserver", "::1"))
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/health", headers={"host": "evil.example"})
    set_settings_override(None)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid host."
