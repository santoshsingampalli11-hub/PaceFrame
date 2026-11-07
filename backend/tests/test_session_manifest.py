"""Synthetic checks for pilot session manifests. Not recording validation."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.annotations.foot_corrections import file_sha256
from app.pilot.session_manifest import (
    SessionManifestError,
    create_session_manifest,
    load_session_manifest,
    main,
    set_manifest_front_leg,
    verify_session_manifest,
)

WIDTH = 32
HEIGHT = 24


def _write_clip(path: Path, brightness: int = 40) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (WIDTH, HEIGHT))
    try:
        if not writer.isOpened():
            pytest.skip("This OpenCV build cannot write an MJPG test clip.")
        for _index in range(4):
            writer.write(np.full((HEIGHT, WIDTH, 3), brightness, np.uint8))
    finally:
        writer.release()


def test_create_and_verify_matching_bytes(tmp_path: Path) -> None:
    video = tmp_path / "delivery.avi"
    output = tmp_path / "sessions" / "B01_D01.json"
    _write_clip(video)
    before = video.read_bytes()
    manifest = create_session_manifest(video, "B01", "D01", output)
    assert manifest.video_sha256 == file_sha256(video)
    assert manifest.video_filename == "delivery.avi"
    assert manifest.camera_side_on_confirmed is False
    assert manifest.full_body_visibility_confirmed is False
    assert manifest.front_leg is None
    assert manifest.source_type == "original_standardized_recording"
    assert manifest.width == WIDTH and manifest.height == HEIGHT
    result = verify_session_manifest(output, video)
    assert result.ok is True
    assert "does not confirm" in result.message
    assert video.read_bytes() == before
    assert not any(path.suffix == ".csv" for path in tmp_path.rglob("*"))


def test_different_bytes_and_same_filename_fail_verification(tmp_path: Path) -> None:
    original = tmp_path / "one" / "clip.avi"
    other_dir = tmp_path / "two"
    other_dir.mkdir()
    other = other_dir / "clip.avi"
    _write_clip(original, 40)
    _write_clip(other, 200)
    manifest_path = tmp_path / "B01_D01.json"
    create_session_manifest(original, "B01", "D01", manifest_path)
    before_manifest = manifest_path.read_bytes()
    result = verify_session_manifest(manifest_path, other)
    assert result.ok is False
    assert "SHA-256 does not match" in result.message
    assert "filename is not video identity" in result.message
    assert original.read_bytes() != other.read_bytes()
    assert manifest_path.read_bytes() == before_manifest
    assert load_session_manifest(manifest_path).video_sha256 == file_sha256(original)


def test_invalid_metadata_does_not_write_a_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    video = tmp_path / "delivery.avi"
    output = tmp_path / "B01_D01.json"
    _write_clip(video)

    def fail_inspect(_path: Path):
        from app.video.inspect import VideoInspection

        return VideoInspection(
            filename="delivery.avi",
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
            warnings=("unreadable",),
            error="OpenCV could not open delivery.avi.",
        )

    monkeypatch.setattr("app.pilot.session_manifest.inspect_video", fail_inspect)
    with pytest.raises(SessionManifestError, match="could not open"):
        create_session_manifest(video, "B01", "D01", output)
    assert not output.exists()


def test_loaded_manifest_rejects_invalid_numbers_and_timestamps(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "bowler_id": "B01",
        "delivery_id": "D01",
        "video_filename": "delivery.avi",
        "video_sha256": "a" * 64,
        "video_path": None,
        "width": 32,
        "height": 24,
        "encoded_fps": 10.0,
        "reported_frame_count": 4,
        "decoded_frame_count": 4,
        "decode_end_status": "counts_agree",
        "source_type": "original_standardized_recording",
        "camera_side_on_confirmed": False,
        "full_body_visibility_confirmed": False,
        "front_leg": None,
        "created_at": "2026-10-12T04:00:00Z",
    }

    def write(name: str, changes: dict[str, object]) -> Path:
        path = tmp_path / name
        body = dict(payload)
        body.update(changes)
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    for name, changes in (
        ("fps-zero.json", {"encoded_fps": 0}),
        ("fps-negative.json", {"encoded_fps": -1}),
        ("bad-time.json", {"created_at": "yesterday"}),
        ("bad-status.json", {"decode_end_status": "bogus"}),
    ):
        with pytest.raises(SessionManifestError):
            load_session_manifest(write(name, changes))

    missing = dict(payload)
    del missing["bowler_id"]
    missing_path = tmp_path / "missing.json"
    missing_path.write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(SessionManifestError, match="not a usable session manifest"):
        load_session_manifest(missing_path)


def test_malformed_json_and_unknown_schema_are_rejected(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(SessionManifestError, match="not valid JSON"):
        load_session_manifest(broken)

    video = tmp_path / "delivery.avi"
    created = tmp_path / "B01_D01.json"
    _write_clip(video)
    create_session_manifest(video, "B01", "D01", created)
    payload = json.loads(created.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SessionManifestError, match="Unsupported manifest schema"):
        load_session_manifest(unknown)


def test_duplicate_output_is_not_overwritten(tmp_path: Path) -> None:
    video = tmp_path / "delivery.avi"
    output = tmp_path / "B01_D01.json"
    _write_clip(video)
    create_session_manifest(video, "B01", "D01", output)
    original = output.read_text(encoding="utf-8")
    with pytest.raises(SessionManifestError, match="already exists"):
        create_session_manifest(video, "B02", "D02", output)
    assert output.read_text(encoding="utf-8") == original


def test_invalid_ids_are_rejected(tmp_path: Path) -> None:
    video = tmp_path / "delivery.avi"
    _write_clip(video)
    for bowler, delivery in (("b01", "D01"), ("B01", "delivery"), ("", "D01"), ("Santosh", "D01")):
        with pytest.raises(SessionManifestError, match="must look like"):
            create_session_manifest(video, bowler, delivery, tmp_path / "out.json")
    assert not (tmp_path / "out.json").exists()


def test_failed_replace_leaves_no_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    video = tmp_path / "delivery.avi"
    output = tmp_path / "sessions" / "B01_D01.json"
    _write_clip(video)

    def fail_replace(_source: str, _destination: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("app.pilot.session_manifest.os.replace", fail_replace)
    with pytest.raises(SessionManifestError, match="Could not write"):
        create_session_manifest(video, "B01", "D01", output)
    assert not output.exists()
    assert list(output.parent.glob("*.tmp")) == []
    assert video.read_bytes()


def test_front_leg_can_be_set_once_and_not_silently_changed(tmp_path: Path) -> None:
    video = tmp_path / "delivery.avi"
    output = tmp_path / "B01_D01.json"
    _write_clip(video)
    create_session_manifest(video, "B01", "D01", output)
    before = json.loads(output.read_text(encoding="utf-8"))
    updated = set_manifest_front_leg(output, "left")
    after = load_session_manifest(output)
    assert updated.front_leg == "left"
    assert after.front_leg == "left"
    assert after.video_sha256 == before["video_sha256"]
    assert after.camera_side_on_confirmed is False
    assert after.full_body_visibility_confirmed is False
    again = set_manifest_front_leg(output, "left")
    assert again.front_leg == "left"
    with pytest.raises(SessionManifestError, match="already has front_leg"):
        set_manifest_front_leg(output, "right")
    assert load_session_manifest(output).front_leg == "left"


def test_cli_create_and_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    video = tmp_path / "delivery.avi"
    output = tmp_path / "B01_D01.json"
    _write_clip(video)
    assert main(["create", "--video", str(video), "--bowler", "B01", "--delivery", "D01", "--output", str(output)]) == 0
    assert "unconfirmed" in capsys.readouterr().out
    assert main(["verify", "--manifest", str(output), "--video", str(video)]) == 0
    other = tmp_path / "other.avi"
    _write_clip(other, 180)
    assert main(["verify", "--manifest", str(output), "--video", str(other)]) == 1
