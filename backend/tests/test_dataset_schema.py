"""Checks that dataset templates exist and have the agreed headers.

The CSVs are schemas only. They must not contain fabricated deliveries
or measurements.
"""

import csv
from pathlib import Path

DATASET = Path(__file__).resolve().parents[2] / "fast_bowling_dataset"

SCHEMAS = {
    DATASET / "metadata" / "bowlers.csv": [
        "bowler_id",
        "delivery_id",
        "recording_date",
        "video_filename",
        "handedness",
        "camera_fps",
        "resolution",
        "camera_view",
        "camera_distance_m",
        "calibration_available",
        "notes",
    ],
    DATASET / "phase_labels" / "phase_labels.csv": [
        "bowler_id",
        "delivery_id",
        "bfc_frame",
        "ffc_frame",
        "release_frame",
        "labeler",
        "notes",
    ],
    DATASET / "measurements" / "biomechanical_measurements.csv": [
        "bowler_id",
        "delivery_id",
        "metric_name",
        "value",
        "unit",
        "phase",
        "notes",
    ],
    DATASET / "validation" / "manual_vs_automatic.csv": [
        "bowler_id",
        "delivery_id",
        "metric_name",
        "manual_value",
        "automatic_value",
        "unit",
        "notes",
    ],
}


def _header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def _data_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return [row for row in rows[1:] if any(cell.strip() for cell in row)]


def test_dataset_template_headers() -> None:
    for path, expected in SCHEMAS.items():
        assert path.is_file(), f"Missing dataset template: {path}"
        assert _header(path) == expected


def test_dataset_templates_have_no_data_rows() -> None:
    for path in SCHEMAS:
        assert _data_rows(path) == [], f"{path.name} must stay a header-only template"


def test_dataset_directories_exist() -> None:
    for relative in ("raw_videos", "metadata", "phase_labels", "landmarks", "measurements", "validation"):
        assert (DATASET / relative).is_dir()


def test_stress_test_folder_is_documented_as_engineering_only() -> None:
    readme = (DATASET / "raw_videos" / "stress_tests" / "README.md").read_text(encoding="utf-8")
    assert "engineering" in readme.lower()
    assert "not" in readme.lower() and "validation" in readme.lower()
