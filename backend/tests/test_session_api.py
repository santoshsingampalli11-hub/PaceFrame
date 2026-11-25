"""HTTP tests for delivery-session upload. Synthetic clips are not bowling data."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.annotations.foot_corrections import file_sha256
from app.api.session_store import (
    InvalidSessionId,
    UploadLimitExceeded,
    client_filename,
    resolve_session_dir,
    save_upload_limited,
)
from app.api.settings import ApiSettings, set_settings_override
from app.main import app
from app.pilot.session_manifest import SessionManifestError, load_session_manifest

WIDTH = 32
HEIGHT = 24
FRAME_COUNT = 4


class _ChunkedUpload:
    def __init__(self, payload: bytes) -> None:
        self._buffer = io.BytesIO(payload)

    async def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


def _write_clip(path: Path, brightness: int = 40) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (WIDTH, HEIGHT))
    try:
        if not writer.isOpened():
            pytest.skip("This OpenCV build cannot write an MJPG test clip.")
        for _index in range(FRAME_COUNT):
            writer.write(np.full((HEIGHT, WIDTH, 3), brightness, np.uint8))
    finally:
        writer.release()


@pytest.fixture
def session_settings(tmp_path: Path):
    settings = ApiSettings(
        session_root=tmp_path / "local_sessions",
        max_upload_bytes=1024 * 1024,
        multipart_overhead_bytes=1024,
    )
    set_settings_override(settings)
    yield settings
    set_settings_override(None)


@pytest.fixture
def client(session_settings: ApiSettings) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _post_session(
    client: TestClient,
    video: Path | bytes,
    *,
    filename: str = "clip.avi",
    content_type: str = "video/x-msvideo",
    bowler_id: str = "B01",
    delivery_id: str = "D01",
    front_leg: str | None = None,
) -> object:
    data = {"bowler_id": bowler_id, "delivery_id": delivery_id}
    if front_leg is not None:
        data["front_leg"] = front_leg
    payload = video.read_bytes() if isinstance(video, Path) else video
    return client.post(
        "/api/sessions",
        data=data,
        files={"video": (filename, payload, content_type)},
    )


def _created_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.iterdir() if path.is_dir()]


def test_valid_upload_creates_session_and_matching_hash(client: TestClient, session_settings: ApiSettings, tmp_path: Path) -> None:
    source = tmp_path / "source.avi"
    _write_clip(source)
    before = source.read_bytes()
    response = _post_session(client, source, front_leg="left")
    assert response.status_code == 200
    body = response.json()
    assert body["bowler_id"] == "B01"
    assert body["delivery_id"] == "D01"
    assert body["video_filename"] == "video.avi"
    assert body["width"] == WIDTH
    assert body["height"] == HEIGHT
    assert body["decoded_frame_count"] == FRAME_COUNT
    assert body["orientation"] == "landscape"
    assert body["status"] == "created"
    assert body["front_leg"] == "left"
    assert body["camera_side_on_confirmed"] is False
    assert body["full_body_visibility_confirmed"] is False
    assert "not mean this video is suitable" in body["scientific_caveat"]
    assert body["session_id"].isalnum() and len(body["session_id"]) == 32
    assert "video_path" not in body
    assert str(session_settings.session_root) not in response.text
    assert "local_sessions" not in response.text

    session_dir = session_settings.session_root / body["session_id"]
    stored = session_dir / "video.avi"
    assert stored.is_file()
    assert stored.read_bytes() == before
    assert body["video_sha256"] == file_sha256(stored)
    assert source.read_bytes() == before
    manifest = load_session_manifest(session_dir / "manifest.json")
    assert manifest.video_sha256 == body["video_sha256"]
    assert manifest.video_filename == "video.avi"
    assert manifest.camera_side_on_confirmed is False
    assert manifest.full_body_visibility_confirmed is False
    assert manifest.front_leg == "left"
    lookup = client.get(f"/api/sessions/{body['session_id']}")
    assert lookup.status_code == 200
    assert lookup.json() == body


def test_unknown_and_invalid_session_ids(client: TestClient) -> None:
    missing = client.get(f"/api/sessions/{'a' * 32}")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Session not found."}
    for session_id in ("not-an-id", "A" * 32, "g" * 32, "a" * 31):
        response = client.get(f"/api/sessions/{session_id}")
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid session id."}
    traversal = client.get("/api/sessions/%2e%2e")
    assert traversal.status_code == 400
    assert traversal.json() == {"detail": "Invalid session id."}
    dotted = client.get("/api/sessions/..")
    assert dotted.status_code in {400, 404}
    assert "detail" in dotted.json()
    for path in ("/api/sessions/../", "/api/sessions/aa/bb"):
        nested = client.get(path)
        assert nested.status_code in {400, 404, 405}
        assert "detail" in nested.json()
        assert nested.status_code != 200


def test_missing_video_and_invalid_identity(client: TestClient, tmp_path: Path) -> None:
    source = tmp_path / "clip.avi"
    _write_clip(source)
    missing = client.post("/api/sessions", data={"bowler_id": "B01", "delivery_id": "D01"})
    assert missing.status_code == 422
    bad_name = _post_session(client, source, bowler_id="Santosh", delivery_id="D01")
    assert bad_name.status_code == 400
    assert "bowler_id" in bad_name.json()["detail"]
    bad_leg = _post_session(client, source, front_leg="front")
    assert bad_leg.status_code == 400


def test_invalid_video_and_unsupported_or_spoofed_types(client: TestClient, session_settings: ApiSettings) -> None:
    invalid = _post_session(client, b"not a video file", filename="clip.mp4", content_type="video/mp4")
    assert invalid.status_code == 400
    assert "detail" in invalid.json()
    assert not _created_dirs(session_settings.session_root)

    archive = _post_session(client, b"PK\x03\x04payload", filename="clip.zip", content_type="video/mp4")
    assert archive.status_code == 415
    assert archive.json() == {"detail": "Unsupported video format."}

    spoofed_archive_name = _post_session(
        client, b"PK\x03\x04payload", filename="clip.avi.zip", content_type="video/x-msvideo"
    )
    assert spoofed_archive_name.status_code == 415


def test_spoofed_mime_still_uses_extension_and_decode(client: TestClient, tmp_path: Path) -> None:
    source = tmp_path / "clip.avi"
    _write_clip(source)
    response = _post_session(client, source, filename="clip.avi", content_type="application/zip")
    assert response.status_code == 200
    assert response.json()["video_filename"] == "video.avi"


def test_oversized_upload_is_413_and_leaves_no_session(client: TestClient, tmp_path: Path) -> None:
    set_settings_override(
        ApiSettings(
            session_root=tmp_path / "local_sessions",
            max_upload_bytes=200,
            multipart_overhead_bytes=64,
        )
    )
    response = _post_session(client, b"x" * 500, filename="clip.avi")
    assert response.status_code == 413
    assert response.json() == {"detail": "Upload exceeds the configured size limit."}
    assert not _created_dirs(tmp_path / "local_sessions")


def test_chunked_copy_enforces_limit_without_leaving_partial_files(tmp_path: Path) -> None:
    destination = tmp_path / "video.avi"
    with pytest.raises(UploadLimitExceeded):
        asyncio.run(
            save_upload_limited(_ChunkedUpload(b"a" * 200), destination, max_bytes=150, chunk_bytes=40)
        )
    assert not destination.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_duplicate_session_id_does_not_overwrite(client: TestClient, session_settings: ApiSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    taken = "ab" * 16
    occupied = session_settings.session_root / taken
    occupied.mkdir(parents=True)
    marker = occupied / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    ids = [taken, "cd" * 16]

    def fake_token(_nbytes: int = 16) -> str:
        return ids.pop(0) if ids else "ef" * 16

    monkeypatch.setattr("app.api.session_store.secrets.token_hex", fake_token)
    source = tmp_path / "clip.avi"
    _write_clip(source)
    response = _post_session(client, source)
    assert response.status_code == 200
    assert response.json()["session_id"] == "cd" * 16
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (occupied / "manifest.json").exists()


def test_exhausted_duplicate_ids_do_not_overwrite(client: TestClient, session_settings: ApiSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    taken = "11" * 16
    occupied = session_settings.session_root / taken
    occupied.mkdir(parents=True)
    marker = occupied / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    monkeypatch.setattr("app.api.session_store.secrets.token_hex", lambda _nbytes=16: taken)
    source = tmp_path / "clip.avi"
    _write_clip(source)
    response = _post_session(client, source)
    assert response.status_code == 409
    assert marker.read_text(encoding="utf-8") == "keep"
    assert list(occupied.iterdir()) == [marker]


def test_failed_manifest_and_incomplete_upload_are_removed(
    client: TestClient, session_settings: ApiSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "clip.avi"
    _write_clip(source)

    def fail_manifest(*_args, **_kwargs):
        raise SessionManifestError("Could not write manifest.json.")

    monkeypatch.setattr("app.api.session_routes.create_session_manifest", fail_manifest)
    failed = _post_session(client, source)
    assert failed.status_code == 400
    assert failed.json()["detail"] == "Could not write manifest.json."
    assert _created_dirs(session_settings.session_root) == []

    async def fail_write(*_args, **_kwargs):
        raise OSError("interrupted")

    monkeypatch.setattr("app.api.session_routes.save_upload_limited", fail_write)
    interrupted = _post_session(client, source)
    assert interrupted.status_code == 500
    assert interrupted.json() == {"detail": "Internal server error"}
    assert str(tmp_path) not in interrupted.text
    assert _created_dirs(session_settings.session_root) == []


def test_existing_health_routes_and_cors(client: TestClient) -> None:
    assert client.get("/").json() == {"name": "Fast Bowling V1", "version": "0.1.0"}
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "healthy"}
    allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    blocked = client.get("/health", headers={"Origin": "http://evil.example"})
    assert blocked.headers.get("access-control-allow-origin") != "http://evil.example"


def test_resolve_and_filename_helpers_reject_traversal(tmp_path: Path) -> None:
    root = tmp_path / "local_sessions"
    root.mkdir()
    for session_id in ("../secret", "..", "a/b", "A" * 32, "g" * 32):
        with pytest.raises(InvalidSessionId):
            resolve_session_dir(root, session_id)
    assert client_filename(r"..\..\evil.zip") == "evil.zip"
    assert client_filename("folder/clip.avi") == "clip.avi"


def test_identifying_client_filename_is_not_returned(client: TestClient, session_settings: ApiSettings, tmp_path: Path) -> None:
    source = tmp_path / "source.avi"
    _write_clip(source)
    response = _post_session(client, source, filename="Santosh_Singampalli_iPhone12.avi")
    assert response.status_code == 200
    body = response.json()
    assert body["video_filename"] == "video.avi"
    assert "Santosh" not in response.text
    assert "iPhone" not in response.text
    record = (session_settings.session_root / body["session_id"] / "session.json").read_text(encoding="utf-8")
    assert "Santosh" not in record
    assert "iPhone" not in record


def test_inspect_error_does_not_leak_filesystem_paths(
    client: TestClient, session_settings: ApiSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "clip.avi"
    _write_clip(source)
    leaked = r"C:\Users\Santosh Singampalli\secret\delivery.mp4"

    def fake_inspect(_path, **_kwargs):
        from app.video.inspect import VideoInspection

        return VideoInspection(
            filename="video.avi",
            width=None,
            height=None,
            orientation=None,
            encoded_fps=None,
            reported_frame_count=None,
            decoded_frame_count=None,
            estimated_duration_seconds=None,
            first_frame_decoded=False,
            decode_end_status="unavailable",
            final_portion_decoded=None,
            warnings=(leaked,),
            error=f"OpenCV failed while reading {leaked}",
        )

    monkeypatch.setattr("app.api.session_routes.inspect_video", fake_inspect)
    response = _post_session(client, source)
    assert response.status_code == 400
    assert leaked not in response.text
    assert "Santosh" not in response.text
    assert response.json() == {"detail": "Video could not be decoded."}
    assert _created_dirs(session_settings.session_root) == []


def test_corrupt_and_incomplete_sessions_are_not_found(
    client: TestClient, session_settings: ApiSettings, tmp_path: Path
) -> None:
    source = tmp_path / "clip.avi"
    _write_clip(source)
    created = _post_session(client, source)
    session_id = created.json()["session_id"]
    session_dir = session_settings.session_root / session_id
    record_path = session_dir / "session.json"
    original = record_path.read_text(encoding="utf-8")

    record_path.write_text("{not json", encoding="utf-8")
    corrupt = client.get(f"/api/sessions/{session_id}")
    assert corrupt.status_code == 404
    assert corrupt.json() == {"detail": "Session not found."}
    assert "not json" not in corrupt.text

    record_path.write_text(
        original.replace('"status": "created"', '"status": "partial"'),
        encoding="utf-8",
    )
    partial = client.get(f"/api/sessions/{session_id}")
    assert partial.status_code == 404

    record_path.write_text(
        original.replace('"orientation": "landscape"', '"orientation": "C:\\\\Users\\\\secret"'),
        encoding="utf-8",
    )
    leaked = client.get(f"/api/sessions/{session_id}")
    assert leaked.status_code == 404
    assert "Users" not in leaked.text
    assert "secret" not in leaked.text

    record_path.write_text(original, encoding="utf-8")
    (session_dir / "video.avi").unlink()
    missing_video = client.get(f"/api/sessions/{session_id}")
    assert missing_video.status_code == 404
    assert missing_video.json() == {"detail": "Session not found."}


def test_failed_session_record_write_cleans_up(
    client: TestClient, session_settings: ApiSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "clip.avi"
    _write_clip(source)

    def fail_record(*_args, **_kwargs):
        from app.api.session_store import SessionStoreError

        raise SessionStoreError("Could not write session.json.")

    monkeypatch.setattr("app.api.session_routes.write_session_record", fail_record)
    response = _post_session(client, source)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "session.json" not in response.text
    assert _created_dirs(session_settings.session_root) == []


def test_request_limit_counts_actual_bytes_without_trusting_content_length(session_settings: ApiSettings) -> None:
    from app.api.settings import get_settings
    from app.api.upload_limit import UploadByteLimitMiddleware

    set_settings_override(
        ApiSettings(
            session_root=session_settings.session_root,
            max_upload_bytes=80,
            multipart_overhead_bytes=20,
        )
    )
    called = {"inner": False}

    async def inner(scope, receive, send):
        called["inner"] = True
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                break
            if message.get("type") == "http.request" and not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    wrapped = UploadByteLimitMiddleware(inner)

    async def run(headers: list[tuple[bytes, bytes]], chunks: list[bytes]) -> int:
        remaining = list(chunks)
        status = {"code": None}

        async def receive():
            if remaining:
                body = remaining.pop(0)
                return {"type": "http.request", "body": body, "more_body": bool(remaining)}
            return {"type": "http.disconnect"}

        async def send(message):
            if message.get("type") == "http.response.start":
                status["code"] = message["status"]

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/sessions",
            "headers": headers,
        }
        await wrapped(scope, receive, send)
        return status["code"]

    missing_header = asyncio.run(run([], [b"a" * 60, b"b" * 60]))
    assert missing_header == 413
    assert called["inner"] is True

    called["inner"] = False
    lying_small_header = asyncio.run(
        run([(b"content-length", b"10")], [b"a" * 60, b"b" * 60])
    )
    assert lying_small_header == 413

    called["inner"] = False
    huge_header = asyncio.run(run([(b"content-length", b"999999")], [b"a" * 10]))
    assert huge_header == 413
    assert called["inner"] is False
    assert get_settings().max_request_bytes == 100
