"""Original-video streaming. Synthetic clips are not bowling data."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.settings import ApiSettings, set_settings_override
from app.api.video_stream import iter_file_span, media_type_for_filename, parse_byte_range, reset_video_stream_cache
from app.api.video_stream import RangeNotSatisfiable
from app.main import app

WIDTH = 16
HEIGHT = 12


def _write_clip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (WIDTH, HEIGHT))
    try:
        if not writer.isOpened():
            pytest.skip("This OpenCV build cannot write an MJPG test clip.")
        for level in (20, 80, 140):
            writer.write(np.full((HEIGHT, WIDTH, 3), level, np.uint8))
    finally:
        writer.release()


@pytest.fixture
def stream_client(tmp_path: Path):
    settings = ApiSettings(
        session_root=tmp_path / "local_sessions",
        max_upload_bytes=1024 * 1024,
        multipart_overhead_bytes=1024,
        max_frame_decodes=1,
    )
    set_settings_override(settings)
    reset_video_stream_cache()
    client = TestClient(app, raise_server_exceptions=False)
    yield client, settings
    reset_video_stream_cache()
    set_settings_override(None)


def _upload(client: TestClient, tmp_path: Path, delivery: str, filename: str = "clip.avi") -> tuple[str, bytes]:
    source = tmp_path / f"{delivery}.avi"
    _write_clip(source)
    payload = source.read_bytes()
    response = client.post(
        "/api/sessions",
        data={"bowler_id": "B01", "delivery_id": delivery},
        files={"video": (filename, payload, "video/x-msvideo")},
    )
    assert response.status_code == 200
    return response.json()["session_id"], payload


def test_playback_does_not_start_pose(
    stream_client: tuple[TestClient, ApiSettings], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _settings = stream_client
    session_id, _payload = _upload(client, tmp_path, "D01")

    def reject(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Pose estimation must not run for video streaming.")

    monkeypatch.setattr("app.pose.mediapipe_estimator.MediaPipePoseEstimator.__init__", reject)
    response = client.get(f"/api/sessions/{session_id}/video", headers={"Range": "bytes=0-7"})
    assert response.status_code == 206
    assert len(response.content) == 8


def test_media_types_follow_the_stored_container() -> None:
    assert media_type_for_filename("video.mp4") == "video/mp4"
    assert media_type_for_filename("video.mov") == "video/quicktime"
    assert media_type_for_filename("video.avi") == "video/x-msvideo"


def test_full_get_head_and_ranges(stream_client: tuple[TestClient, ApiSettings], tmp_path: Path) -> None:
    client, settings = stream_client
    session_id, payload = _upload(client, tmp_path, "D01")
    stored = settings.session_root / session_id / "video.avi"
    before = stored.read_bytes()

    full = client.get(f"/api/sessions/{session_id}/video")
    assert full.status_code == 200
    assert full.headers["content-type"].startswith("video/x-msvideo")
    assert full.headers["accept-ranges"] == "bytes"
    assert int(full.headers["content-length"]) == len(payload)
    assert full.content == payload
    assert "local_sessions" not in full.headers.get("content-disposition", "")

    head = client.head(f"/api/sessions/{session_id}/video")
    assert head.status_code == 200
    assert int(head.headers["content-length"]) == len(payload)
    assert head.content == b""

    partial = client.get(f"/api/sessions/{session_id}/video", headers={"Range": "bytes=0-3"})
    assert partial.status_code == 206
    assert partial.content == payload[:4]
    assert partial.headers["content-range"] == f"bytes 0-3/{len(payload)}"
    assert int(partial.headers["content-length"]) == 4

    opened = client.get(f"/api/sessions/{session_id}/video", headers={"Range": "bytes=2-"})
    assert opened.status_code == 206
    assert opened.content == payload[2:]
    assert opened.headers["content-range"] == f"bytes 2-{len(payload) - 1}/{len(payload)}"

    suffix = client.get(f"/api/sessions/{session_id}/video", headers={"Range": "bytes=-4"})
    assert suffix.status_code == 206
    assert suffix.content == payload[-4:]

    last = len(payload) - 1
    exact = client.get(f"/api/sessions/{session_id}/video", headers={"Range": f"bytes={last}-{last}"})
    assert exact.status_code == 206
    assert exact.content == payload[-1:]
    assert stored.read_bytes() == before

    frame = client.get(f"/api/sessions/{session_id}/video/frames/0")
    assert frame.status_code == 200
    assert frame.headers["content-type"].startswith("image/jpeg")


def test_unsatisfiable_malformed_and_multiple_ranges(
    stream_client: tuple[TestClient, ApiSettings], tmp_path: Path
) -> None:
    client, _settings = stream_client
    session_id, payload = _upload(client, tmp_path, "D01")
    outside = client.get(
        f"/api/sessions/{session_id}/video",
        headers={"Range": f"bytes={len(payload)}-{len(payload)}"},
    )
    assert outside.status_code == 416
    assert outside.headers["content-range"] == f"bytes */{len(payload)}"
    assert outside.content == b""

    malformed = client.get(f"/api/sessions/{session_id}/video", headers={"Range": "bytes=abc"})
    assert malformed.status_code == 416
    many = client.get(f"/api/sessions/{session_id}/video", headers={"Range": "bytes=0-1,2-3"})
    assert many.status_code == 416
    assert many.headers["content-range"] == f"bytes */{len(payload)}"
    backwards = client.get(f"/api/sessions/{session_id}/video", headers={"Range": "bytes=8-2"})
    assert backwards.status_code == 416


def test_unknown_invalid_and_traversal_do_not_open_other_files(
    stream_client: tuple[TestClient, ApiSettings],
) -> None:
    client, _settings = stream_client
    missing = client.get(f"/api/sessions/{'ab' * 16}/video")
    assert missing.status_code == 404
    invalid = client.get("/api/sessions/not-an-id/video")
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "Invalid session id."
    escaped = client.get("/api/sessions/..%2F..%2Fvideo/video")
    assert escaped.status_code in {400, 404, 422}
    assert "local_sessions" not in escaped.text


def test_tamper_is_rejected_and_sessions_stay_isolated(
    stream_client: tuple[TestClient, ApiSettings], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, settings = stream_client
    first, first_bytes = _upload(client, tmp_path, "D01")
    second, second_bytes = _upload(client, tmp_path, "D02")
    one = client.get(f"/api/sessions/{first}/video")
    two = client.get(f"/api/sessions/{second}/video")
    assert one.content == first_bytes
    assert two.content == second_bytes
    assert one.content != two.content or first_bytes == second_bytes

    video = settings.session_root / first / "video.avi"
    video.write_bytes(first_bytes + b"x")
    tampered = client.get(f"/api/sessions/{first}/video")
    assert tampered.status_code == 400
    assert tampered.json()["detail"] == "Video does not match the session manifest."
    assert video.read_bytes() == first_bytes + b"x"

    reset_video_stream_cache()
    calls = {"count": 0}
    from app.pilot import session_manifest

    real_hash = session_manifest.file_sha256

    def counting(path: object) -> str:
        calls["count"] += 1
        return real_hash(path)

    monkeypatch.setattr(session_manifest, "file_sha256", counting)
    again = client.get(f"/api/sessions/{second}/video")
    cached = client.get(f"/api/sessions/{second}/video")
    assert again.status_code == cached.status_code == 200
    assert calls["count"] == 1


def test_iterator_closes_the_file(tmp_path: Path) -> None:
    path = tmp_path / "clip.bin"
    path.write_bytes(b"abcdefghij")
    stream = iter_file_span(path, 2, 5)
    assert next(stream) == b"cdef"
    stream.close()
    path.unlink()
    with pytest.raises(RangeNotSatisfiable):
        parse_byte_range("bytes=-0", 10)
    with pytest.raises(RangeNotSatisfiable):
        parse_byte_range("bytes=0-0", 0)
