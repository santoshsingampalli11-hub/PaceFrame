"""Exact original-frame JPEG retrieval. Synthetic clips are not bowling data."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.settings import ApiSettings, set_settings_override
from app.api.video_frames import reset_frame_service
from app.main import app
from app.video.reader import iter_frames

WIDTH = 32
HEIGHT = 24
LEVELS = (20, 80, 140, 200)


def _write_clip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (WIDTH, HEIGHT))
    try:
        if not writer.isOpened():
            pytest.skip("This OpenCV build cannot write an MJPG test clip.")
        for level in LEVELS:
            writer.write(np.full((HEIGHT, WIDTH, 3), level, np.uint8))
    finally:
        writer.release()


def _mean(jpeg: bytes) -> float:
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return float(image.mean())


@pytest.fixture
def frame_client(tmp_path: Path):
    settings = ApiSettings(
        session_root=tmp_path / "local_sessions",
        max_upload_bytes=1024 * 1024,
        multipart_overhead_bytes=1024,
        max_frame_decodes=1,
    )
    set_settings_override(settings)
    reset_frame_service()
    client = TestClient(app, raise_server_exceptions=False)
    yield client, settings
    reset_frame_service()
    set_settings_override(None)


def _upload(client: TestClient, tmp_path: Path, delivery: str) -> tuple[str, bytes]:
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


def test_first_middle_and_last_frames_match_decode_order(frame_client: tuple[TestClient, ApiSettings], tmp_path: Path) -> None:
    client, settings = frame_client
    session_id, before = _upload(client, tmp_path, "D01")
    stored = settings.session_root / session_id / "video.avi"
    for index, level in ((0, LEVELS[0]), (2, LEVELS[2]), (len(LEVELS) - 1, LEVELS[-1])):
        response = client.get(f"/api/sessions/{session_id}/video/frames/{index}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/jpeg")
        assert abs(_mean(response.content) - level) < 12
    assert stored.read_bytes() == before
    assert client.get(f"/api/sessions/{session_id}/video.avi").status_code == 404


def test_indexes_outside_the_video_are_rejected(frame_client: tuple[TestClient, ApiSettings], tmp_path: Path) -> None:
    client, _settings = frame_client
    session_id, _before = _upload(client, tmp_path, "D01")
    assert client.get(f"/api/sessions/{session_id}/video/frames/{len(LEVELS)}").status_code == 400
    assert client.get(f"/api/sessions/{session_id}/video/frames/-1").status_code in {400, 404}
    malformed = client.get(f"/api/sessions/{session_id}/video/frames/nope")
    assert malformed.status_code in {400, 404, 422}
    traversal = client.get(f"/api/sessions/{session_id}/video/frames/..%2Fvideo.avi")
    assert traversal.status_code in {400, 404, 422}
    assert "local_sessions" not in malformed.text


def test_unknown_corrupt_missing_and_changed_video(
    frame_client: tuple[TestClient, ApiSettings], tmp_path: Path
) -> None:
    client, settings = frame_client
    missing = client.get(f"/api/sessions/{'ab' * 16}/video/frames/0")
    assert missing.status_code == 404
    assert client.get("/api/sessions/not-an-id/video/frames/0").status_code == 400

    session_id, before = _upload(client, tmp_path, "D01")
    manifest = settings.session_root / session_id / "manifest.json"
    original_manifest = manifest.read_text(encoding="utf-8")
    manifest.write_text("{not json", encoding="utf-8")
    assert client.get(f"/api/sessions/{session_id}/video/frames/0").status_code == 404
    manifest.write_text(original_manifest, encoding="utf-8")

    video = settings.session_root / session_id / "video.avi"
    video.unlink()
    assert client.get(f"/api/sessions/{session_id}/video/frames/0").status_code == 404

    session_id, before = _upload(client, tmp_path, "D02")
    video = settings.session_root / session_id / "video.avi"
    video.write_bytes(before + b"xxxx")
    changed = client.get(f"/api/sessions/{session_id}/video/frames/0")
    assert changed.status_code == 400
    assert changed.json()["detail"] == "Video does not match the session manifest."


def test_decode_closes_the_reader_and_does_not_run_pose(
    frame_client: tuple[TestClient, ApiSettings], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _settings = frame_client
    session_id, _before = _upload(client, tmp_path, "D01")
    closed: list[bool] = []

    def tracking(path: object):
        stream = iter_frames(path)
        try:
            yield from stream
        finally:
            closed.append(True)
            stream.close()

    monkeypatch.setattr("app.api.video_frames.iter_frames", tracking)

    def reject_pose(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Pose estimation must not run for an original frame.")

    monkeypatch.setattr("app.pose.mediapipe_estimator.MediaPipePoseEstimator.__init__", reject_pose)
    response = client.get(f"/api/sessions/{session_id}/video/frames/1")
    assert response.status_code == 200
    assert closed == []
    reset_frame_service()
    assert closed == [True]


def test_capacity_cross_session_and_cache(
    frame_client: tuple[TestClient, ApiSettings], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, settings = frame_client
    first, _one = _upload(client, tmp_path, "D01")
    second_source = tmp_path / "other.avi"
    _write_clip(second_source)
    brighter = bytearray(second_source.read_bytes())
    second = client.post(
        "/api/sessions",
        data={"bowler_id": "B01", "delivery_id": "D02"},
        files={"video": ("clip.avi", bytes(brighter), "video/x-msvideo")},
    )
    assert second.status_code == 200
    second_id = second.json()["session_id"]
    calls = {"count": 0}
    real = iter_frames

    def counting(path: object):
        calls["count"] += 1
        return real(path)

    monkeypatch.setattr("app.api.video_frames.iter_frames", counting)
    one = client.get(f"/api/sessions/{first}/video/frames/0")
    again = client.get(f"/api/sessions/{first}/video/frames/0")
    other = client.get(f"/api/sessions/{second_id}/video/frames/0")
    assert one.status_code == again.status_code == other.status_code == 200
    assert again.content == one.content
    assert calls["count"] == 2
    assert one.content != other.content or abs(_mean(one.content) - _mean(other.content)) < 12

    monkeypatch.setattr("app.api.video_frames._acquire_slot", lambda: False)
    blocked = client.get(f"/api/sessions/{first}/video/frames/3")
    assert blocked.status_code == 503
    assert blocked.json()["detail"] == "Frame decoding capacity is full."
    assert (settings.session_root / first / "video.avi").is_file()


def test_forward_resume_and_previous_frame_cache(
    frame_client: tuple[TestClient, ApiSettings], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, settings = frame_client
    session_id, before = _upload(client, tmp_path, "D01")
    calls = {"count": 0}
    real = iter_frames

    def counting(path: object):
        calls["count"] += 1
        return real(path)

    monkeypatch.setattr("app.api.video_frames.iter_frames", counting)
    first = client.get(f"/api/sessions/{session_id}/video/frames/0")
    second = client.get(f"/api/sessions/{session_id}/video/frames/1")
    assert first.status_code == second.status_code == 200
    assert calls["count"] == 1
    assert abs(_mean(first.content) - LEVELS[0]) < 12
    assert abs(_mean(second.content) - LEVELS[1]) < 12

    reset_frame_service()
    calls["count"] = 0
    jumped = client.get(f"/api/sessions/{session_id}/video/frames/2")
    previous = client.get(f"/api/sessions/{session_id}/video/frames/1")
    assert jumped.status_code == previous.status_code == 200
    assert calls["count"] == 1
    assert abs(_mean(jumped.content) - LEVELS[2]) < 12
    assert abs(_mean(previous.content) - LEVELS[1]) < 12
    assert (settings.session_root / session_id / "video.avi").read_bytes() == before
