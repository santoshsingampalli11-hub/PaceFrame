"""HTTP tests for pose-review jobs. Fake estimators are not MediaPipe accuracy checks."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.pose_review_jobs import (
    STATUS_RUNNING,
    PoseReviewJob,
    get_job_runner,
    pose_review_dir,
    reset_job_runner,
    save_job,
    set_estimator_factory,
    utc_now,
)
from app.api.settings import ApiSettings, set_settings_override
from app.main import app
from app.pose.estimator import PoseEstimationError
from app.pose.landmarks import Landmark, PoseFrame
from app.video import VideoFrame

WIDTH = 32
HEIGHT = 24
FRAME_COUNT = 4


class _FakeEstimator:
    def __init__(self, *, mode: str = "all", gate: threading.Event | None = None) -> None:
        self.mode = mode
        self.gate = gate
        self.started = threading.Event()
        self.closed = False
        self.seen: list[int] = []

    def estimate(self, frame: VideoFrame) -> PoseFrame:
        self.started.set()
        if self.gate is not None and not self.gate.wait(timeout=5):
            raise PoseEstimationError("test gate timed out")
        if self.mode == "fail":
            raise PoseEstimationError("pose stopped")
        self.seen.append(frame.index)
        detected = self.mode == "all" or (self.mode == "even" and frame.index % 2 == 0)
        landmarks = {}
        if detected:
            landmarks = {"nose": Landmark("nose", 0.5, 0.2, 0.9, 0.8)}
        return PoseFrame(
            frame_index=frame.index,
            timestamp_seconds=frame.timestamp_seconds,
            image_width=frame.image.shape[1],
            image_height=frame.image.shape[0],
            landmarks=landmarks,
        )

    def close(self) -> None:
        self.closed = True


def _write_clip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (WIDTH, HEIGHT))
    try:
        if not writer.isOpened():
            pytest.skip("This OpenCV build cannot write an MJPG test clip.")
        for index in range(FRAME_COUNT):
            writer.write(np.full((HEIGHT, WIDTH, 3), 30 + index, np.uint8))
    finally:
        writer.release()


@pytest.fixture
def pose_settings(tmp_path: Path):
    settings = ApiSettings(
        session_root=tmp_path / "local_sessions",
        max_upload_bytes=1024 * 1024,
        multipart_overhead_bytes=1024,
        max_pose_jobs=1,
        max_review_frames=8,
    )
    set_settings_override(settings)
    reset_job_runner()
    yield settings
    reset_job_runner()
    set_estimator_factory(None)
    set_settings_override(None)


@pytest.fixture
def client(pose_settings: ApiSettings) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _upload(client: TestClient, tmp_path: Path, delivery: str = "D01") -> tuple[str, Path, bytes]:
    source = tmp_path / f"{delivery}.avi"
    _write_clip(source)
    before = source.read_bytes()
    response = client.post(
        "/api/sessions",
        data={"bowler_id": "B01", "delivery_id": delivery},
        files={"video": ("clip.avi", before, "video/x-msvideo")},
    )
    assert response.status_code == 200
    return response.json()["session_id"], source, before


def _factory(estimator: _FakeEstimator):
    def make() -> _FakeEstimator:
        return estimator

    set_estimator_factory(make)
    reset_job_runner()
    get_job_runner()
    return estimator


def test_successful_job_submission_status_and_report(client: TestClient, pose_settings: ApiSettings, tmp_path: Path) -> None:
    session_id, source, before = _upload(client, tmp_path)
    estimator = _factory(_FakeEstimator())
    created = client.post(f"/api/sessions/{session_id}/pose-review", json={})
    assert created.status_code == 202
    body = created.json()
    assert body["session_id"] == session_id
    assert body["status"] in {"queued", "running"}
    assert body["status_path"] == f"/api/sessions/{session_id}/pose-review"
    assert "not a scientifically suitable" in body["scientific_caveat"] or "not a 2D" in body["scientific_caveat"]
    assert get_job_runner().wait_until_idle()
    status = client.get(f"/api/sessions/{session_id}/pose-review")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["job_id"] == body["job_id"]
    report = client.get(f"/api/sessions/{session_id}/pose-review/report")
    assert report.status_code == 200
    payload = report.json()
    assert payload["status"] == "completed"
    assert payload["decoded_frame_count"] == FRAME_COUNT
    assert payload["pose_frames"] == FRAME_COUNT
    assert payload["missing_pose_count"] == 0
    assert "Not bowler identity" in payload["report_text"]
    assert "biomechanical measurement" in payload["scientific_caveat"]
    assert estimator.closed is True
    assert estimator.seen == list(range(FRAME_COUNT))
    assert source.read_bytes() == before
    stored = pose_settings.session_root / session_id / "video.avi"
    assert stored.read_bytes() == before
    assert str(pose_settings.session_root) not in report.text


def test_pending_report_is_rejected(client: TestClient, tmp_path: Path) -> None:
    session_id, _source, _before = _upload(client, tmp_path)
    gate = threading.Event()
    estimator = _factory(_FakeEstimator(gate=gate))
    created = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [0]})
    assert created.status_code == 202
    assert estimator.started.wait(timeout=5)
    pending = client.get(f"/api/sessions/{session_id}/pose-review/report")
    assert pending.status_code == 409
    assert pending.json() == {"detail": "Pose review is not complete."}
    status = client.get(f"/api/sessions/{session_id}/pose-review")
    assert status.json()["status"] in {"queued", "running"}
    gate.set()
    assert get_job_runner().wait_until_idle()
    assert client.get(f"/api/sessions/{session_id}/pose-review/report").status_code == 200


def test_failed_inference_does_not_return_a_report(client: TestClient, pose_settings: ApiSettings, tmp_path: Path) -> None:
    session_id, source, before = _upload(client, tmp_path)
    _factory(_FakeEstimator(mode="fail"))
    created = client.post(f"/api/sessions/{session_id}/pose-review", json={})
    assert created.status_code == 202
    assert get_job_runner().wait_until_idle()
    status = client.get(f"/api/sessions/{session_id}/pose-review")
    assert status.json()["status"] == "failed"
    failed = client.get(f"/api/sessions/{session_id}/pose-review/report")
    assert failed.status_code == 409
    assert "pose stopped" in failed.json()["detail"] or failed.json()["detail"] == "Pose review failed."
    assert not (pose_settings.session_root / session_id / "pose_review" / "report.txt").exists()
    assert source.read_bytes() == before


def test_missing_model_and_init_failure(client: TestClient, tmp_path: Path) -> None:
    session_id, _source, _before = _upload(client, tmp_path)

    def missing():
        raise PoseEstimationError("MediaPipe pose model not found at pose_landmarker_full.task.")

    set_estimator_factory(missing)
    reset_job_runner()
    created = client.post(f"/api/sessions/{session_id}/pose-review", json={})
    assert created.status_code == 202
    assert get_job_runner().wait_until_idle()
    assert client.get(f"/api/sessions/{session_id}/pose-review").json()["status"] == "failed"
    assert "pose_landmarker_full.task" in client.get(f"/api/sessions/{session_id}/pose-review/report").json()["detail"]

    def broken():
        raise PoseEstimationError("MediaPipe could not load the pose model pose_landmarker_full.task.")

    set_estimator_factory(broken)
    reset_job_runner()
    again = client.post(f"/api/sessions/{session_id}/pose-review", json={})
    assert again.status_code == 202
    assert get_job_runner().wait_until_idle()
    assert client.get(f"/api/sessions/{session_id}/pose-review").json()["status"] == "failed"


def test_duplicate_and_capacity(client: TestClient, tmp_path: Path) -> None:
    first, _s1, _b1 = _upload(client, tmp_path, "D01")
    second, _s2, _b2 = _upload(client, tmp_path, "D02")
    gate = threading.Event()
    current = {"estimator": _FakeEstimator(gate=gate)}

    def make() -> _FakeEstimator:
        return current["estimator"]

    set_estimator_factory(make)
    reset_job_runner()
    started = client.post(f"/api/sessions/{first}/pose-review", json={})
    assert started.status_code == 202
    assert current["estimator"].started.wait(timeout=5)
    duplicate = client.post(f"/api/sessions/{first}/pose-review", json={})
    assert duplicate.status_code == 409
    other = client.post(f"/api/sessions/{second}/pose-review", json={})
    assert other.status_code == 503
    assert other.json() == {"detail": "Pose review capacity is full."}
    gate.set()
    assert get_job_runner().wait_until_idle()
    current["estimator"] = _FakeEstimator()
    follow = client.post(f"/api/sessions/{second}/pose-review", json={})
    assert follow.status_code == 202
    assert get_job_runner().wait_until_idle()


def test_invalid_frames_unknown_session_and_traversal(client: TestClient, tmp_path: Path) -> None:
    session_id, _source, _before = _upload(client, tmp_path)
    _factory(_FakeEstimator())
    negative = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [-1]})
    assert negative.status_code == 400
    repeated = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [1, 1]})
    assert repeated.status_code == 400
    boolean = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [True]})
    assert boolean.status_code in {400, 422}
    too_many = client.post(
        f"/api/sessions/{session_id}/pose-review",
        json={"review_frames": list(range(9))},
    )
    assert too_many.status_code == 400
    missing = client.post(f"/api/sessions/{'a' * 32}/pose-review", json={})
    assert missing.status_code == 404
    invalid = client.post("/api/sessions/not-an-id/pose-review", json={})
    assert invalid.status_code == 400
    traversal = client.get("/api/sessions/%2e%2e/pose-review")
    assert traversal.status_code == 400


def test_corrupt_manifest_and_changed_bytes(client: TestClient, pose_settings: ApiSettings, tmp_path: Path) -> None:
    session_id, _source, before = _upload(client, tmp_path)
    _factory(_FakeEstimator())
    manifest = pose_settings.session_root / session_id / "manifest.json"
    manifest.write_text("{not json", encoding="utf-8")
    corrupt = client.post(f"/api/sessions/{session_id}/pose-review", json={})
    assert corrupt.status_code == 404
    manifest.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    session_id, _source, before = _upload(client, tmp_path, "D03")
    video = pose_settings.session_root / session_id / "video.avi"
    video.write_bytes(before + b"xxxx")
    changed = client.post(f"/api/sessions/{session_id}/pose-review", json={})
    assert changed.status_code == 400
    assert changed.json() == {"detail": "Video does not match the session manifest."}


def test_interrupted_job_is_not_left_running(client: TestClient, pose_settings: ApiSettings, tmp_path: Path) -> None:
    session_id, _source, _before = _upload(client, tmp_path)
    session_dir = pose_settings.session_root / session_id
    save_job(
        session_dir,
        PoseReviewJob(
            job_id="ab" * 16,
            session_id=session_id,
            status=STATUS_RUNNING,
            message="Pose review is running.",
            created_at=utc_now(),
            started_at=utc_now(),
            finished_at=None,
            review_frames=(),
            error=None,
        ),
    )
    report = pose_review_dir(session_dir) / "report.txt"
    report.write_text("should not stay completed", encoding="utf-8")
    reset_job_runner()
    _factory(_FakeEstimator())
    status = client.get(f"/api/sessions/{session_id}/pose-review")
    assert status.status_code == 200
    assert status.json()["status"] == "failed"
    assert "interrupted" in status.json()["message"].lower()
    failed = client.get(f"/api/sessions/{session_id}/pose-review/report")
    assert failed.status_code == 409
    assert not report.exists()


def test_health_and_upload_routes_still_work(client: TestClient) -> None:
    assert client.get("/").json()["name"] == "Fast Bowling V1"
    assert client.get("/health").json() == {"status": "healthy"}
    assert client.post("/health").status_code == 405


def test_completed_review_serves_only_exported_overlay_pngs(
    client: TestClient, pose_settings: ApiSettings, tmp_path: Path
) -> None:
    session_id, source, before = _upload(client, tmp_path)
    other_id, _other, _other_bytes = _upload(client, tmp_path, "D02")
    _factory(_FakeEstimator())
    gate = threading.Event()
    pending = _FakeEstimator(gate=gate)
    set_estimator_factory(lambda: pending)
    reset_job_runner()
    started = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [0, 2]})
    assert started.status_code == 202
    assert pending.started.wait(timeout=5)
    early = client.get(f"/api/sessions/{session_id}/pose-review/frames/0")
    assert early.status_code == 409
    gate.set()
    assert get_job_runner().wait_until_idle()
    report = client.get(f"/api/sessions/{session_id}/pose-review/report")
    assert report.status_code == 200
    assert report.json()["overlay_frames"] == [0, 2]
    image = client.get(f"/api/sessions/{session_id}/pose-review/frames/0")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content.startswith(b"\x89PNG")
    missing = client.get(f"/api/sessions/{session_id}/pose-review/frames/1")
    assert missing.status_code == 404
    invalid = client.get(f"/api/sessions/{session_id}/pose-review/frames/-1")
    assert invalid.status_code in {400, 404}
    traversal = client.get(f"/api/sessions/{session_id}/pose-review/frames/..%2Fvideo.avi")
    assert traversal.status_code in {400, 404, 422}
    other = client.get(f"/api/sessions/{other_id}/pose-review/frames/0")
    assert other.status_code == 404
    video = client.get(f"/api/sessions/{session_id}/video.avi")
    assert video.status_code == 404
    assert source.read_bytes() == before
    stored = pose_settings.session_root / session_id / "video.avi"
    assert stored.read_bytes() == before


def test_failed_review_does_not_serve_an_overlay(client: TestClient, pose_settings: ApiSettings, tmp_path: Path) -> None:
    session_id, _source, _before = _upload(client, tmp_path)
    _factory(_FakeEstimator(mode="fail"))
    created = client.post(f"/api/sessions/{session_id}/pose-review", json={"review_frames": [0]})
    assert created.status_code == 202
    assert get_job_runner().wait_until_idle()
    image = client.get(f"/api/sessions/{session_id}/pose-review/frames/0")
    assert image.status_code == 409
    assert not (pose_settings.session_root / session_id / "pose_review" / "frame_0.png").exists()
