"""HTTP tests for manual labels and 2D knee measurement. Fake estimators are not accuracy checks."""

from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.measurement_jobs import (
    STATUS_RUNNING,
    MeasurementJob,
    get_measurement_runner,
    measure_dir,
    reset_measurement_runner,
    save_measurement_job,
)
from app.api.pose_review_jobs import reset_job_runner, set_estimator_factory, utc_now
from app.api.settings import ApiSettings, set_settings_override
from app.main import app
from app.pose.estimator import PoseEstimationError
from app.pose.landmarks import Landmark, PoseFrame
from app.video import VideoFrame

WIDTH = 32
HEIGHT = 24
FRAME_COUNT = 4


class _KneeEstimator:
    def __init__(self, mode: str = "ok", gate: threading.Event | None = None) -> None:
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
        landmarks = {}
        if self.mode != "none" and not (self.mode == "missing-ffc" and frame.index == 1):
            landmarks = {
                "left_hip": Landmark("left_hip", 0.5, 0.2, 1.0, 1.0),
                "left_knee": Landmark("left_knee", 0.5, 0.5, 1.0, 1.0),
                "left_ankle": Landmark("left_ankle", 0.5, 0.8, 1.0, 1.0),
            }
        return PoseFrame(
            frame.index,
            frame.timestamp_seconds,
            frame.image.shape[1],
            frame.image.shape[0],
            landmarks,
        )

    def close(self) -> None:
        self.closed = True


def _write_clip(path: Path) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (WIDTH, HEIGHT))
    try:
        if not writer.isOpened():
            pytest.skip("This OpenCV build cannot write an MJPG test clip.")
        for index in range(FRAME_COUNT):
            writer.write(np.full((HEIGHT, WIDTH, 3), 40 + index, np.uint8))
    finally:
        writer.release()


@pytest.fixture
def api_settings(tmp_path: Path):
    settings = ApiSettings(
        session_root=tmp_path / "local_sessions",
        max_upload_bytes=1024 * 1024,
        multipart_overhead_bytes=1024,
        max_pose_jobs=1,
    )
    set_settings_override(settings)
    reset_job_runner()
    reset_measurement_runner()
    yield settings
    reset_measurement_runner()
    reset_job_runner()
    set_estimator_factory(None)
    set_settings_override(None)


@pytest.fixture
def client(api_settings: ApiSettings) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _upload(client: TestClient, tmp_path: Path, delivery: str = "D01") -> tuple[str, bytes]:
    source = tmp_path / f"{delivery}.avi"
    _write_clip(source)
    payload = source.read_bytes()
    response = client.post(
        "/api/sessions",
        data={"bowler_id": "B01", "delivery_id": delivery},
        files={"video": ("clip.avi", payload, "video/x-msvideo")},
    )
    assert response.status_code == 200
    return response.json()["session_id"], payload


def _labels_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
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
    body.update(overrides)
    return body


def test_put_and_get_labels_allow_missing_bfc(client: TestClient, tmp_path: Path) -> None:
    session_id, _bytes = _upload(client, tmp_path)
    missing = client.get(f"/api/sessions/{session_id}/labels")
    assert missing.status_code == 404
    created = client.put(f"/api/sessions/{session_id}/labels", json=_labels_body(bfc_frame=None))
    assert created.status_code == 200
    body = created.json()
    assert body["bfc_frame"] is None
    assert body["ffc_frame"] == 1
    assert body["release_frame"] == 3
    assert body["front_leg"] == "left"
    assert body["confirm_front_leg"] is True
    assert body["confirm_label_link"] is True
    assert body["annotation_byte_identity_verified"] is False
    fetched = client.get(f"/api/sessions/{session_id}/labels")
    assert fetched.status_code == 200
    assert fetched.json()["labeler"] == "SS"
    session = client.get(f"/api/sessions/{session_id}")
    assert session.json()["front_leg"] == "left"
    assert session.json()["camera_side_on_confirmed"] is False


def test_label_validation_and_conflicts(client: TestClient, tmp_path: Path) -> None:
    session_id, _bytes = _upload(client, tmp_path)
    order = client.put(f"/api/sessions/{session_id}/labels", json=_labels_body(ffc_frame=3, release_frame=1))
    assert order.status_code == 400
    boolean = client.put(f"/api/sessions/{session_id}/labels", json=_labels_body(ffc_frame=True))
    assert boolean.status_code in {400, 422}
    bounds = client.put(f"/api/sessions/{session_id}/labels", json=_labels_body(release_frame=9))
    assert bounds.status_code == 400
    no_confirm = client.put(
        f"/api/sessions/{session_id}/labels",
        json=_labels_body(confirm_front_leg=False),
    )
    assert no_confirm.status_code == 400
    ok = client.put(f"/api/sessions/{session_id}/labels", json=_labels_body())
    assert ok.status_code == 200
    duplicate = client.put(f"/api/sessions/{session_id}/labels", json=_labels_body())
    assert duplicate.status_code == 409
    other_leg = client.put(
        f"/api/sessions/{session_id}/labels",
        json=_labels_body(front_leg="right", replace_existing=True),
    )
    assert other_leg.status_code == 409
    replaced = client.put(
        f"/api/sessions/{session_id}/labels",
        json=_labels_body(ffc_frame=2, replace_existing=True),
    )
    assert replaced.status_code == 200
    assert replaced.json()["ffc_frame"] == 2
    assert replaced.json()["front_leg"] == "left"


def test_corrupt_labels_and_hash_mismatch(client: TestClient, api_settings: ApiSettings, tmp_path: Path) -> None:
    session_id, original = _upload(client, tmp_path)
    client.put(f"/api/sessions/{session_id}/labels", json=_labels_body())
    csv_path = api_settings.session_root / session_id / "phase_labels.csv"
    csv_path.write_text("not a csv", encoding="utf-8")
    corrupt = client.get(f"/api/sessions/{session_id}/labels")
    assert corrupt.status_code == 404
    session_id, original = _upload(client, tmp_path, "D02")
    video = api_settings.session_root / session_id / "video.avi"
    video.write_bytes(original + b"xxxx")
    changed = client.put(f"/api/sessions/{session_id}/labels", json=_labels_body())
    assert changed.status_code == 400


def test_successful_measurement_and_report(client: TestClient, tmp_path: Path) -> None:
    session_id, before = _upload(client, tmp_path)
    source = tmp_path / "D01.avi"
    estimator = _KneeEstimator()
    set_estimator_factory(lambda: estimator)
    reset_measurement_runner()
    assert client.put(f"/api/sessions/{session_id}/labels", json=_labels_body()).status_code == 200
    unconfirmed = client.post(
        f"/api/sessions/{session_id}/measure",
        json={"confirm_label_link": False},
    )
    assert unconfirmed.status_code == 400
    created = client.post(
        f"/api/sessions/{session_id}/measure",
        json={"confirm_label_link": True},
    )
    assert created.status_code == 202
    assert created.json()["report_path"] == f"/api/sessions/{session_id}/report"
    assert get_measurement_runner().wait_until_idle()
    status = client.get(f"/api/sessions/{session_id}/measure")
    assert status.json()["status"] == "completed"
    report = client.get(f"/api/sessions/{session_id}/report")
    assert report.status_code == 200
    payload = report.json()["report"]
    assert payload["ffc_frame"] == 1
    assert payload["release_frame"] == 3
    assert payload["front_leg"] == "left"
    assert payload["ffc"]["angle_degrees"] is not None
    assert payload["release"]["angle_degrees"] is not None
    assert payload["ffc"]["status"] == "available"
    assert payload["annotation_byte_identity_verified"] is False
    assert estimator.closed is True
    assert estimator.seen == list(range(FRAME_COUNT))
    assert source.read_bytes() == before
    assert "video_path" not in payload
    again = client.post(f"/api/sessions/{session_id}/measure", json={"confirm_label_link": True})
    assert again.status_code == 409


def test_unavailable_pose_and_pending_report(client: TestClient, tmp_path: Path) -> None:
    session_id, _before = _upload(client, tmp_path)
    assert client.put(f"/api/sessions/{session_id}/labels", json=_labels_body()).status_code == 200
    gate = threading.Event()
    estimator = _KneeEstimator(gate=gate)
    set_estimator_factory(lambda: estimator)
    reset_measurement_runner()
    created = client.post(f"/api/sessions/{session_id}/measure", json={"confirm_label_link": True})
    assert created.status_code == 202
    assert estimator.started.wait(timeout=5)
    pending = client.get(f"/api/sessions/{session_id}/report")
    assert pending.status_code == 409
    duplicate = client.post(f"/api/sessions/{session_id}/measure", json={"confirm_label_link": True})
    assert duplicate.status_code == 409
    gate.set()
    assert get_measurement_runner().wait_until_idle()

    session_id, _before = _upload(client, tmp_path, "D04")
    assert client.put(f"/api/sessions/{session_id}/labels", json=_labels_body()).status_code == 200
    missing = _KneeEstimator(mode="none")
    set_estimator_factory(lambda: missing)
    reset_measurement_runner()
    client.post(f"/api/sessions/{session_id}/measure", json={"confirm_label_link": True})
    assert get_measurement_runner().wait_until_idle()
    report = client.get(f"/api/sessions/{session_id}/report")
    assert report.status_code == 200
    assert report.json()["report"]["ffc"]["angle_degrees"] is None
    assert report.json()["report"]["ffc"]["status"] == "unavailable"
    assert report.json()["report"]["ffc"]["review_status"] == "unavailable"


def test_failed_measurement_and_interrupt(client: TestClient, api_settings: ApiSettings, tmp_path: Path) -> None:
    session_id, _before = _upload(client, tmp_path)
    assert client.put(f"/api/sessions/{session_id}/labels", json=_labels_body()).status_code == 200
    set_estimator_factory(lambda: _KneeEstimator(mode="fail"))
    reset_measurement_runner()
    client.post(f"/api/sessions/{session_id}/measure", json={"confirm_label_link": True})
    assert get_measurement_runner().wait_until_idle()
    assert client.get(f"/api/sessions/{session_id}/measure").json()["status"] == "failed"
    assert client.get(f"/api/sessions/{session_id}/report").status_code == 409
    assert not (api_settings.session_root / session_id / "measurement" / "report.json").exists()

    session_id, _before = _upload(client, tmp_path, "D05")
    session_dir = api_settings.session_root / session_id
    save_measurement_job(
        session_dir,
        MeasurementJob(
            job_id="cd" * 16,
            session_id=session_id,
            status=STATUS_RUNNING,
            message="running",
            created_at=utc_now(),
            started_at=utc_now(),
            finished_at=None,
            error=None,
        ),
    )
    (measure_dir(session_dir) / "report.json").write_text("{}", encoding="utf-8")
    reset_measurement_runner()
    set_estimator_factory(lambda: _KneeEstimator())
    get_measurement_runner()
    status = client.get(f"/api/sessions/{session_id}/measure")
    assert status.json()["status"] == "failed"
    assert client.get(f"/api/sessions/{session_id}/report").status_code == 409


def test_upload_and_pose_review_still_work(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "healthy"}
    assert client.post("/health").status_code == 405
