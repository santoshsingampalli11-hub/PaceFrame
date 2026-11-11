"""Synthetic checks for manual-phase front-knee measurement. Not validation."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.annotations.models import PhaseLabel
from app.annotations.phase_labels import write_phase_labels
from app.annotations.video_identity import remember_video_filename
from app.biomechanics.front_knee import front_knee_angles_at_manual_phases
from app.pilot.manual_measurement import measure_manual_front_knee
from app.pilot.session_manifest import create_session_manifest
from app.pose.estimator import PoseEstimationError
from app.pose.landmarks import Landmark, PoseFrame
from app.video import VideoFrame

WIDTH = 40
HEIGHT = 30


def _write_clip(path: Path, brightness: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (WIDTH, HEIGHT))
    try:
        if not writer.isOpened():
            pytest.skip("This OpenCV build cannot write an MJPG test clip.")
        for index in range(4):
            writer.write(np.full((HEIGHT, WIDTH, 3), brightness + index, np.uint8))
    finally:
        writer.release()


def _labels(path: Path, ffc: int | None = 1, release: int | None = 3, bowler: str = "B01") -> None:
    write_phase_labels(
        path,
        [PhaseLabel(bowler, "D01", ffc_frame=ffc, release_frame=release, labeler="TEST")],
    )


class _Estimator:
    def __init__(self, mode: str = "straight") -> None:
        self.mode = mode
        self.closed = False
        self.seen: list[int] = []

    def estimate(self, frame: VideoFrame) -> PoseFrame:
        self.seen.append(frame.index)
        if self.mode == "fail":
            raise PoseEstimationError("pose stopped")
        if self.mode == "bad-index":
            index = frame.index + 5
        else:
            index = frame.index
        landmarks = {}
        if self.mode != "none" and not (self.mode == "missing-ffc" and frame.index == 1):
            ankle_x = 0.5 if frame.index != 1 else 0.8
            ankle_y = 0.8 if frame.index != 1 else 0.5
            landmarks = {
                "left_hip": Landmark("left_hip", 0.5, 0.2, 1.0, 1.0),
                "left_knee": Landmark("left_knee", 0.5, 0.5, 1.0, 1.0),
                "left_ankle": Landmark("left_ankle", ankle_x, ankle_y, 1.0, 1.0),
            }
        return PoseFrame(index, frame.timestamp_seconds, frame.image.shape[1], frame.image.shape[0], landmarks)

    def close(self) -> None:
        self.closed = True


def _session(tmp_path: Path, *, front_leg: str | None = "left", brightness: int = 30) -> tuple[Path, Path, Path]:
    video = tmp_path / "delivery.avi"
    manifest = tmp_path / "B01_D01.json"
    labels = tmp_path / "phase_labels.csv"
    _write_clip(video, brightness)
    create_session_manifest(video, "B01", "D01", manifest, front_leg)
    return video, manifest, labels


def test_verified_session_measures_exact_manual_frames(tmp_path: Path) -> None:
    video, manifest, labels = _session(tmp_path)
    _labels(labels)
    remember_video_filename(labels, "B01", "D01", video.name)
    before_video = video.read_bytes()
    before_labels = labels.read_bytes()
    before_manifest = manifest.read_bytes()
    estimator = _Estimator()
    output = tmp_path / "result.json"
    attempt = measure_manual_front_knee(
        video, manifest, labels, output, confirm_label_link=True, estimator=estimator
    )
    assert attempt.ok is True
    assert estimator.closed is True
    assert estimator.seen == [0, 1, 2, 3]
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["video_byte_identity_verified"] is True
    assert report["annotation_byte_identity_verified"] is False
    assert report["annotation_provenance"] == "human_confirmed_filename_sidecar"
    assert report["front_leg"] == "left"
    assert report["ffc_frame"] == 1
    assert report["release_frame"] == 3
    assert report["release"]["angle_degrees"] == pytest.approx(180.0)
    assert report["release"]["status"] == "available"
    assert report["release"]["source"] == "raw_2d_mediapipe_landmarks"
    assert report["ffc"]["frame_index"] == 1
    assert report["ffc"]["angle_degrees"] != pytest.approx(report["release"]["angle_degrees"])
    assert report["camera_side_on_confirmed"] is False
    assert "not scientific approval" in " ".join(report["warnings"])
    assert "reference angle" in " ".join(report["limitations"]).lower() or "No manual reference" in " ".join(report["limitations"])
    assert video.read_bytes() == before_video
    assert labels.read_bytes() == before_labels
    assert manifest.read_bytes() == before_manifest
    direct_estimator = _Estimator()
    direct_poses = [
        direct_estimator.estimate(VideoFrame(index, index / 10, np.zeros((HEIGHT, WIDTH, 3), np.uint8)))
        for index in range(4)
    ]
    label = PhaseLabel("B01", "D01", ffc_frame=1, release_frame=3)
    ffc, release = front_knee_angles_at_manual_phases(direct_poses, label, "left")
    assert report["ffc"]["angle_degrees"] == pytest.approx(ffc.angle_degrees)
    assert report["release"]["angle_degrees"] == pytest.approx(release.angle_degrees)


def test_hash_mismatch_missing_manifest_and_missing_front_leg_do_not_measure(tmp_path: Path) -> None:
    video, manifest, labels = _session(tmp_path)
    _labels(labels)
    remember_video_filename(labels, "B01", "D01", video.name)
    other = tmp_path / "other.avi"
    _write_clip(other, 200)
    estimator = _Estimator()
    mismatch = measure_manual_front_knee(
        other, manifest, labels, tmp_path / "mismatch.json", confirm_label_link=True, estimator=estimator
    )
    assert mismatch.ok is False
    assert mismatch.output_path is None
    assert "SHA-256" in mismatch.message
    assert estimator.seen == []
    assert not (tmp_path / "mismatch.json").exists()

    missing = measure_manual_front_knee(
        video, tmp_path / "absent.json", labels, tmp_path / "missing.json", confirm_label_link=True, estimator=estimator
    )
    assert missing.ok is False
    assert "not found" in missing.message.lower()

    no_leg_video, no_leg_manifest, no_leg_labels = _session(tmp_path / "noleg", front_leg=None)
    _labels(no_leg_labels)
    remember_video_filename(no_leg_labels, "B01", "D01", no_leg_video.name)
    no_leg = measure_manual_front_knee(
        no_leg_video, no_leg_manifest, no_leg_labels, tmp_path / "noleg.json", confirm_label_link=True, estimator=estimator
    )
    assert no_leg.ok is False
    assert "front leg" in no_leg.message
    assert estimator.seen == []


def test_label_linkage_must_be_explicit(tmp_path: Path) -> None:
    video, manifest, labels = _session(tmp_path)
    _labels(labels)
    estimator = _Estimator()
    missing_sidecar = measure_manual_front_knee(
        video, manifest, labels, tmp_path / "out.json", confirm_label_link=True, estimator=estimator
    )
    assert missing_sidecar.ok is False
    assert "does not prove" in missing_sidecar.message

    remember_video_filename(labels, "B01", "D01", "other.avi")
    wrong_name = measure_manual_front_knee(
        video, manifest, labels, tmp_path / "out.json", confirm_label_link=True, estimator=estimator
    )
    assert wrong_name.ok is False
    assert "other.avi" in wrong_name.message

    remember_video_filename(labels, "B01", "D01", video.name)
    unconfirmed = measure_manual_front_knee(
        video, manifest, labels, tmp_path / "out.json", confirm_label_link=False, estimator=estimator
    )
    assert unconfirmed.ok is False
    assert "confirm-label-link" in unconfirmed.message
    assert estimator.seen == []
    assert not (tmp_path / "out.json").exists()


def test_missing_and_duplicate_labels_stop(tmp_path: Path) -> None:
    video, manifest, labels = _session(tmp_path)
    write_phase_labels(labels, [PhaseLabel("B02", "D09", ffc_frame=1, release_frame=2)])
    remember_video_filename(labels, "B01", "D01", video.name)
    missing = measure_manual_front_knee(
        video, manifest, labels, tmp_path / "out.json", confirm_label_link=True, estimator=_Estimator()
    )
    assert missing.ok is False
    assert "found 0" in missing.message

    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text(
        "bowler_id,delivery_id,bfc_frame,ffc_frame,release_frame,labeler,notes\n"
        "B01,D01,,1,3,TEST,\n"
        "B01,D01,,1,3,TEST,\n",
        encoding="utf-8",
    )
    remember_video_filename(duplicate, "B01", "D01", video.name)
    rejected = measure_manual_front_knee(
        video, manifest, duplicate, tmp_path / "dup.json", confirm_label_link=True, estimator=_Estimator()
    )
    assert rejected.ok is False
    assert "Duplicate" in rejected.message


def test_missing_pose_and_missing_frame_are_unavailable(tmp_path: Path) -> None:
    video, manifest, labels = _session(tmp_path)
    _labels(labels, ffc=1, release=3)
    remember_video_filename(labels, "B01", "D01", video.name)
    one_missing = measure_manual_front_knee(
        video, manifest, labels, tmp_path / "one.json", confirm_label_link=True, estimator=_Estimator("missing-ffc")
    )
    one_report = json.loads(one_missing.output_path.read_text(encoding="utf-8"))
    assert one_report["ffc"]["angle_degrees"] is None
    assert one_report["ffc"]["status"] == "unavailable"
    assert one_report["release"]["angle_degrees"] == pytest.approx(180.0)

    both = measure_manual_front_knee(
        video, manifest, labels, tmp_path / "both.json", confirm_label_link=True, estimator=_Estimator("none")
    )
    both_report = json.loads(both.output_path.read_text(encoding="utf-8"))
    assert both_report["ffc"]["angle_degrees"] is None
    assert both_report["release"]["angle_degrees"] is None

    far_labels = tmp_path / "far.csv"
    _labels(far_labels, ffc=1, release=20)
    remember_video_filename(far_labels, "B01", "D01", video.name)
    far = measure_manual_front_knee(
        video, manifest, far_labels, tmp_path / "far.json", confirm_label_link=True, estimator=_Estimator()
    )
    far_report = json.loads(far.output_path.read_text(encoding="utf-8"))
    assert far_report["release"]["angle_degrees"] is None
    assert "neighboring frame was not used" in far_report["release"]["reason"]


def test_bad_frame_index_and_pose_failure_do_not_write_a_success(tmp_path: Path) -> None:
    video, manifest, labels = _session(tmp_path)
    _labels(labels)
    remember_video_filename(labels, "B01", "D01", video.name)
    bad = _Estimator("bad-index")
    attempt = measure_manual_front_knee(
        video, manifest, labels, tmp_path / "bad.json", confirm_label_link=True, estimator=bad
    )
    assert attempt.ok is False
    assert "does not match decoded frame" in attempt.message
    assert bad.closed is True
    assert not (tmp_path / "bad.json").exists()

    failed = _Estimator("fail")
    stopped = measure_manual_front_knee(
        video, manifest, labels, tmp_path / "fail.json", confirm_label_link=True, estimator=failed
    )
    assert stopped.ok is False
    assert failed.closed is True
    assert "pose stopped" in stopped.message
    assert not (tmp_path / "fail.json").exists()


def test_failed_report_write_leaves_no_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    video, manifest, labels = _session(tmp_path)
    _labels(labels)
    remember_video_filename(labels, "B01", "D01", video.name)

    def fail_replace(_source: str, _destination: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("app.pilot.manual_measurement.os.replace", fail_replace)
    output = tmp_path / "sessions" / "result.json"
    attempt = measure_manual_front_knee(
        video, manifest, labels, output, confirm_label_link=True, estimator=_Estimator()
    )
    assert attempt.ok is False
    assert "Could not write" in attempt.message
    assert not output.exists()
    assert list(output.parent.glob("*.tmp")) == []


def test_reused_verification_skips_a_second_inspection_until_the_bytes_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video, manifest, labels = _session(tmp_path)
    _labels(labels)
    remember_video_filename(labels, "B01", "D01", video.name)
    from app.pilot.manual_measurement import capture_verified_video
    from app.pilot.session_manifest import load_session_manifest, verify_session_manifest

    assert verify_session_manifest(manifest, video).ok
    verified = capture_verified_video(video, load_session_manifest(manifest).video_sha256)
    calls = {"n": 0}
    import app.pilot.session_manifest as manifest_module

    real_inspect = manifest_module.inspect_video

    def counting(path: Path) -> object:
        calls["n"] += 1
        return real_inspect(path)

    monkeypatch.setattr(manifest_module, "inspect_video", counting)
    direct = _Estimator()
    reused = measure_manual_front_knee(
        video,
        manifest,
        labels,
        tmp_path / "reused.json",
        confirm_label_link=True,
        estimator=direct,
        verified_video=verified,
    )
    assert reused.ok is True
    assert calls["n"] == 0
    assert direct.seen == [0, 1, 2, 3]
    full = measure_manual_front_knee(
        video,
        manifest,
        labels,
        tmp_path / "full.json",
        confirm_label_link=True,
        estimator=_Estimator(),
    )
    assert full.ok is True
    assert calls["n"] == 1
    reused_report = json.loads((tmp_path / "reused.json").read_text(encoding="utf-8"))
    full_report = json.loads((tmp_path / "full.json").read_text(encoding="utf-8"))
    assert reused_report["ffc"]["angle_degrees"] == full_report["ffc"]["angle_degrees"]
    assert reused_report["release"]["angle_degrees"] == full_report["release"]["angle_degrees"]
    assert reused_report["ffc"]["frame_index"] == 1
    assert reused_report["release"]["frame_index"] == 3

    other_manifest_sha = "a" * 64
    foreign = capture_verified_video(video, other_manifest_sha)
    foreign_estimator = _Estimator()
    isolated = measure_manual_front_knee(
        video,
        manifest,
        labels,
        tmp_path / "isolated.json",
        confirm_label_link=True,
        estimator=foreign_estimator,
        verified_video=foreign,
    )
    assert isolated.ok is True
    assert calls["n"] == 2
    assert foreign_estimator.seen == [0, 1, 2, 3]

    _write_clip(video, brightness=180)
    tampered = _Estimator()
    rejected = measure_manual_front_knee(
        video,
        manifest,
        labels,
        tmp_path / "tampered.json",
        confirm_label_link=True,
        estimator=tampered,
        verified_video=verified,
    )
    assert rejected.ok is False
    assert "SHA-256" in rejected.message
    assert tampered.seen == []
    assert not (tmp_path / "tampered.json").exists()
