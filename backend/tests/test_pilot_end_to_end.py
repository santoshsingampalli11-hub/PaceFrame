"""One synthetic pass through inspect, manifest, labels, and knee measurement.

The numbers check the software path. They are not a validation of bowling.
"""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.annotations.models import PhaseLabel
from app.annotations.phase_labels import write_phase_labels
from app.annotations.video_identity import remember_video_filename
from app.biomechanics.front_knee import front_knee_angles_at_manual_phases
from app.biomechanics.geometry import Point2D, angle_abc_degrees
from app.pilot.manual_measurement import measure_manual_front_knee
from app.pilot.session_manifest import create_session_manifest, verify_session_manifest
from app.pose.landmarks import Landmark, PoseFrame
from app.video import VideoFrame
from app.video.inspect import inspect_video

WIDTH = 40
HEIGHT = 30


def _write_clip(path: Path, brightness: int = 40) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (WIDTH, HEIGHT))
    try:
        if not writer.isOpened():
            pytest.skip("This OpenCV build cannot write an MJPG test clip.")
        for index in range(4):
            writer.write(np.full((HEIGHT, WIDTH, 3), brightness + index, np.uint8))
    finally:
        writer.release()


def _pose(frame: VideoFrame) -> PoseFrame:
    ankle = (0.8, 0.3) if frame.index == 1 else (0.5, 0.8)
    return PoseFrame(
        frame.index,
        frame.timestamp_seconds,
        frame.image.shape[1],
        frame.image.shape[0],
        {
            "left_hip": Landmark("left_hip", 0.5, 0.2, 1.0, 1.0),
            "left_knee": Landmark("left_knee", 0.5, 0.5, 1.0, 1.0),
            "left_ankle": Landmark("left_ankle", ankle[0], ankle[1], 1.0, 1.0),
        },
    )


class _Estimator:
    def __init__(self) -> None:
        self.closed = False
        self.poses: list[PoseFrame] = []

    def estimate(self, frame: VideoFrame) -> PoseFrame:
        pose = _pose(frame)
        self.poses.append(pose)
        return pose

    def close(self) -> None:
        self.closed = True


def test_synthetic_pilot_workflow_from_inspect_to_measurement(tmp_path: Path) -> None:
    video = tmp_path / "delivery.avi"
    manifest_path = tmp_path / "sessions" / "B01_D01.json"
    labels = tmp_path / "phase_labels.csv"
    report_path = tmp_path / "sessions" / "B01_D01_measurement.json"
    _write_clip(video)
    before_video = video.read_bytes()

    inspection = inspect_video(video)
    assert inspection.error is None
    assert inspection.decode_end_status == "counts_agree"
    assert inspection.width == WIDTH and inspection.height == HEIGHT

    manifest = create_session_manifest(video, "B01", "D01", manifest_path, "left")
    assert manifest.video_sha256
    assert manifest.camera_side_on_confirmed is False
    assert manifest.full_body_visibility_confirmed is False
    verified = verify_session_manifest(manifest_path, video)
    assert verified.ok is True

    write_phase_labels(labels, [PhaseLabel("B01", "D01", bfc_frame=0, ffc_frame=1, release_frame=3, labeler="TEST")])
    remember_video_filename(labels, "B01", "D01", video.name)
    before_labels = labels.read_bytes()
    before_manifest = manifest_path.read_bytes()

    estimator = _Estimator()
    attempt = measure_manual_front_knee(
        video, manifest_path, labels, report_path, confirm_label_link=True, estimator=estimator
    )
    assert attempt.ok is True
    assert estimator.closed is True
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["bowler_id"] == "B01" and report["delivery_id"] == "D01"
    assert report["video_sha256"] == manifest.video_sha256
    assert report["video_byte_identity_verified"] is True
    assert report["annotation_byte_identity_verified"] is False
    assert report["annotation_provenance"] == "human_confirmed_filename_sidecar"
    assert "not a SHA-256" in " ".join(report["warnings"]) or "does not store a video hash" in " ".join(report["warnings"])
    assert report["front_leg"] == "left"
    assert report["ffc_frame"] == 1 and report["release_frame"] == 3
    assert report["camera_side_on_confirmed"] is False
    assert report["ffc"]["status"] == "available"
    assert report["ffc"]["source"] == "raw_2d_mediapipe_landmarks"
    assert [item["role"] for item in report["ffc"]["evidence"]] == ["hip", "knee", "ankle"]
    assert report["release"]["angle_degrees"] == pytest.approx(180.0)
    assert report["release"]["review_status"] == "no_structural_warning"
    pixel_angle = angle_abc_degrees(
        Point2D(0.5 * WIDTH, 0.2 * HEIGHT),
        Point2D(0.5 * WIDTH, 0.5 * HEIGHT),
        Point2D(0.8 * WIDTH, 0.3 * HEIGHT),
    )
    normalized_angle = angle_abc_degrees(Point2D(0.5, 0.2), Point2D(0.5, 0.5), Point2D(0.8, 0.3))
    assert pixel_angle != pytest.approx(normalized_angle)
    assert report["ffc"]["angle_degrees"] == pytest.approx(pixel_angle)
    direct_ffc, direct_release = front_knee_angles_at_manual_phases(
        estimator.poses, PhaseLabel("B01", "D01", ffc_frame=1, release_frame=3), "left"
    )
    assert report["ffc"]["angle_degrees"] == pytest.approx(direct_ffc.angle_degrees)
    assert report["release"]["angle_degrees"] == pytest.approx(direct_release.angle_degrees)
    assert "accuracy statistic" in " ".join(report["limitations"]) or "No manual reference" in " ".join(report["limitations"])

    again = measure_manual_front_knee(
        video, manifest_path, labels, report_path, confirm_label_link=True, estimator=_Estimator()
    )
    assert again.ok is False
    assert "already exists" in again.message
    assert video.read_bytes() == before_video
    assert labels.read_bytes() == before_labels
    assert manifest_path.read_bytes() == before_manifest


def test_wrong_delivery_is_not_measured(tmp_path: Path) -> None:
    video = tmp_path / "delivery.avi"
    manifest_path = tmp_path / "B01_D01.json"
    labels = tmp_path / "phase_labels.csv"
    _write_clip(video)
    create_session_manifest(video, "B01", "D01", manifest_path, "left")
    write_phase_labels(labels, [PhaseLabel("B01", "D02", ffc_frame=1, release_frame=3)])
    remember_video_filename(labels, "B01", "D02", video.name)
    attempt = measure_manual_front_knee(
        video, manifest_path, labels, tmp_path / "out.json", confirm_label_link=True, estimator=_Estimator()
    )
    assert attempt.ok is False
    assert "D01" in attempt.message
    assert "found 0" in attempt.message
    assert not (tmp_path / "out.json").exists()
