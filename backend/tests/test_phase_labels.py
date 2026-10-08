"""Tests for manual phase-label annotations. No videos, pose, or FastAPI."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.annotations import (
    PHASE_LABEL_FIELDNAMES,
    AnnotationError,
    PhaseLabel,
    read_phase_labels,
    upsert_phase_label,
    upsert_phase_label_file,
    validate_phase_labels,
    write_phase_labels,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATASET_PHASE_LABELS = (
    Path(__file__).resolve().parents[2] / "fast_bowling_dataset" / "phase_labels" / "phase_labels.csv"
)
HEADER = ",".join(PHASE_LABEL_FIELDNAMES)


def _label(
    bowler: str = "B01",
    delivery: str = "D01",
    bfc: int | None = 10,
    ffc: int | None = 20,
    release: int | None = 30,
    labeler: str = "SS",
    notes: str = "",
) -> PhaseLabel:
    return PhaseLabel(
        bowler_id=bowler,
        delivery_id=delivery,
        bfc_frame=bfc,
        ffc_frame=ffc,
        release_frame=release,
        labeler=labeler,
        notes=notes,
    )


def test_annotations_import_without_video_pose_or_api() -> None:
    check = (
        "import sys, app.annotations; "
        "assert 'fastapi' not in sys.modules; "
        "assert 'cv2' not in sys.modules; "
        "assert 'mediapipe' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", check], cwd=BACKEND_DIR, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr


# --- model / validation ----------------------------------------------------


def test_fully_labeled_valid_delivery() -> None:
    label = _label()
    assert label.key == ("B01", "D01")
    assert (label.bfc_frame, label.ffc_frame, label.release_frame) == (10, 20, 30)


def test_all_phases_none() -> None:
    label = _label(bfc=None, ffc=None, release=None)
    assert label.bfc_frame is None
    assert label.ffc_frame is None
    assert label.release_frame is None


def test_partially_labeled_delivery() -> None:
    bfc_only = _label(bfc=100, ffc=None, release=None)
    bfc_and_ffc = _label(bfc=100, ffc=140, release=None)
    bfc_and_release = _label(bfc=100, ffc=None, release=130)
    assert bfc_only.ffc_frame is None and bfc_only.release_frame is None
    assert bfc_and_ffc.release_frame is None
    assert bfc_and_release.ffc_frame is None


@pytest.mark.parametrize("field", ["bfc", "ffc", "release"])
def test_negative_phase_frame_is_rejected(field: str) -> None:
    kwargs = {"bfc": 10, "ffc": 20, "release": 30, field: -1}
    with pytest.raises(AnnotationError, match=">= 0"):
        _label(**kwargs)


def test_bfc_equal_to_ffc_is_rejected() -> None:
    with pytest.raises(AnnotationError, match="earlier"):
        _label(bfc=10, ffc=10, release=30)


def test_ffc_equal_to_release_is_rejected() -> None:
    with pytest.raises(AnnotationError, match="earlier"):
        _label(bfc=10, ffc=20, release=20)


def test_bfc_after_ffc_is_rejected() -> None:
    with pytest.raises(AnnotationError, match="earlier"):
        _label(bfc=20, ffc=10, release=30)


def test_ffc_after_release_is_rejected() -> None:
    with pytest.raises(AnnotationError, match="earlier"):
        _label(bfc=10, ffc=40, release=30)


def test_bfc_not_earlier_than_release_when_ffc_missing() -> None:
    with pytest.raises(AnnotationError, match="earlier"):
        _label(bfc=130, ffc=None, release=100)
    with pytest.raises(AnnotationError, match="earlier"):
        _label(bfc=100, ffc=None, release=100)


def test_non_integer_frame_is_rejected() -> None:
    with pytest.raises(AnnotationError, match="integer"):
        PhaseLabel(bowler_id="B01", delivery_id="D01", bfc_frame=10.0)
    with pytest.raises(AnnotationError, match="integer"):
        PhaseLabel(bowler_id="B01", delivery_id="D01", ffc_frame=True)


def test_frame_outside_total_count_is_rejected() -> None:
    label = _label(bfc=10, ffc=20, release=30)
    with pytest.raises(AnnotationError, match="outside"):
        validate_phase_labels(label, total_frame_count=30)


def test_frame_equal_to_total_count_is_rejected() -> None:
    label = _label(bfc=0, ffc=1, release=9)
    with pytest.raises(AnnotationError, match="outside"):
        validate_phase_labels(label, total_frame_count=9)


def test_last_legal_frame_is_accepted() -> None:
    label = _label(bfc=0, ffc=1, release=9)
    validate_phase_labels(label, total_frame_count=10)


def test_empty_bowler_id_is_rejected() -> None:
    with pytest.raises(AnnotationError, match="bowler_id"):
        _label(bowler="", delivery="D01")


def test_whitespace_only_delivery_id_is_rejected() -> None:
    with pytest.raises(AnnotationError, match="delivery_id"):
        _label(bowler="B01", delivery="   ")


def test_ids_are_stripped() -> None:
    label = _label(bowler=" B01 ", delivery=" D01 ")
    assert label.bowler_id == "B01"
    assert label.delivery_id == "D01"


def test_invalid_total_frame_count_is_rejected() -> None:
    label = _label()
    with pytest.raises(AnnotationError, match="total_frame_count"):
        validate_phase_labels(label, total_frame_count=0)
    with pytest.raises(AnnotationError, match="total_frame_count"):
        validate_phase_labels(label, total_frame_count=-5)


# --- CSV -------------------------------------------------------------------


def test_header_only_csv(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text(HEADER + "\n", encoding="utf-8")

    assert read_phase_labels(path) == ()


def test_dataset_template_is_header_only() -> None:
    assert read_phase_labels(DATASET_PHASE_LABELS) == ()


def test_valid_single_row_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    original = _label(notes="side-on take")
    write_phase_labels(path, [original])

    loaded = read_phase_labels(path)
    assert loaded == (original,)
    assert "None" not in path.read_text(encoding="utf-8")


def test_multiple_rows_preserve_file_order(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    first = _label(bowler="B02", delivery="D01", bfc=1, ffc=2, release=3)
    second = _label(bowler="B01", delivery="D02", bfc=4, ffc=5, release=6)
    write_phase_labels(path, [first, second])

    assert read_phase_labels(path) == (first, second)


def test_blank_phase_cells_become_none(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text(
        HEADER + "\nB01,D01,,,,SS,partial\n",
        encoding="utf-8",
    )

    (label,) = read_phase_labels(path)
    assert label.bfc_frame is None
    assert label.ffc_frame is None
    assert label.release_frame is None
    assert label.labeler == "SS"
    assert label.notes == "partial"


def test_none_phases_write_blank_cells(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    write_phase_labels(path, [_label(bfc=None, ffc=None, release=None)])
    body = path.read_text(encoding="utf-8").splitlines()[1]
    assert body.startswith("B01,D01,,,,SS")


def test_malformed_integer_cell_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text(HEADER + "\nB01,D01,10.5,20,30,SS,\n", encoding="utf-8")

    with pytest.raises(AnnotationError, match="not a non-negative integer"):
        read_phase_labels(path)


def test_missing_required_column_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text("bowler_id,delivery_id,bfc_frame\nB01,D01,10\n", encoding="utf-8")

    with pytest.raises(AnnotationError, match="missing columns"):
        read_phase_labels(path)


def test_unexpected_extra_column_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    extra = HEADER + ",score\nB01,D01,10,20,30,SS,,0.9\n"
    path.write_text(extra, encoding="utf-8")

    with pytest.raises(AnnotationError, match="unexpected columns"):
        read_phase_labels(path)


def test_duplicate_key_rows_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text(
        HEADER + "\nB01,D01,10,20,30,SS,\nB01,D01,11,21,31,SS,\n",
        encoding="utf-8",
    )

    with pytest.raises(AnnotationError, match="Duplicate"):
        read_phase_labels(path)


def test_round_trip_preserves_partial_and_full_labels(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    labels = (
        _label(bfc=8, ffc=None, release=None, notes="BFC only"),
        _label(bowler="B01", delivery="D02", bfc=8, ffc=12, release=18, labeler="AB"),
    )
    write_phase_labels(path, labels)
    assert read_phase_labels(path) == labels


# --- upsert ----------------------------------------------------------------


def test_upsert_adds_new_delivery() -> None:
    existing = (_label(bowler="B01", delivery="D01"),)
    added = upsert_phase_label(existing, _label(bowler="B01", delivery="D02", bfc=1, ffc=2, release=3))
    assert [item.key for item in added] == [("B01", "D01"), ("B01", "D02")]


def test_upsert_updates_existing_delivery_without_duplicate() -> None:
    existing = (
        _label(bowler="B02", delivery="D01", bfc=1, ffc=2, release=3),
        _label(bowler="B01", delivery="D01", bfc=4, ffc=5, release=6),
    )
    updated = _label(bowler="B02", delivery="D01", bfc=7, ffc=8, release=9, notes="revised")
    result = upsert_phase_label(existing, updated)

    assert result[0] == updated
    assert result[1] == existing[1]
    assert [item.key for item in result] == [("B02", "D01"), ("B01", "D01")]


def test_upsert_file_creates_and_updates(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "phase_labels.csv"
    first = _label()
    upsert_phase_label_file(path, first)
    second = _label(bfc=11, ffc=21, release=31, notes="updated")
    result = upsert_phase_label_file(path, second)

    assert path.is_file()
    assert result == (second,)
    assert read_phase_labels(path) == (second,)


def test_write_rejects_duplicate_keys(tmp_path: Path) -> None:
    with pytest.raises(AnnotationError, match="Duplicate"):
        write_phase_labels(
            tmp_path / "phase_labels.csv",
            [_label(), _label(bfc=11, ffc=21, release=31)],
        )
    assert not (tmp_path / "phase_labels.csv").exists()


# --- file safety -----------------------------------------------------------


def test_missing_input_file_uses_filename_only(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    with pytest.raises(FileNotFoundError, match="missing.csv") as caught:
        read_phase_labels(missing)
    assert str(tmp_path) not in str(caught.value)


def test_write_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "phase_labels.csv"
    write_phase_labels(path, [_label()])
    assert read_phase_labels(path) == (_label(),)


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_bytes(b"")
    with pytest.raises(AnnotationError, match="no CSV header"):
        read_phase_labels(path)


def test_invalid_utf8_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(AnnotationError, match="not valid UTF-8"):
        read_phase_labels(path)


def test_utf8_bom_header_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_bytes(b"\xef\xbb\xbf" + (HEADER + "\n").encode("utf-8"))
    assert read_phase_labels(path) == ()


def test_whitespace_frame_cell_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text(HEADER + "\nB01,D01, 10 ,20,30,SS,\n", encoding="utf-8")
    (label,) = read_phase_labels(path)
    assert label.bfc_frame == 10


def test_negative_frame_cell_in_csv_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text(HEADER + "\nB01,D01,-1,20,30,SS,\n", encoding="utf-8")
    with pytest.raises(AnnotationError, match="not a non-negative integer"):
        read_phase_labels(path)


def test_notes_with_comma_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    original = _label(notes="side-on, 30 fps")
    write_phase_labels(path, [original])
    assert read_phase_labels(path) == (original,)


def test_upsert_does_not_mutate_input() -> None:
    existing = [_label()]
    upsert_phase_label(existing, _label(delivery="D02", bfc=1, ffc=2, release=3))
    assert existing == [_label()]


def test_reading_a_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AnnotationError, match="not a file"):
        read_phase_labels(tmp_path)


def test_failed_replace_leaves_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "phase_labels.csv"
    original = _label(notes="keep")
    write_phase_labels(path, [original])
    before = path.read_bytes()

    def boom(_src: str | os.PathLike[str], _dst: str | os.PathLike[str]) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(AnnotationError, match="Could not write phase_labels.csv"):
        write_phase_labels(path, [_label(notes="should not land")])

    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_duplicate_header_names_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text(
        "bowler_id,delivery_id,bfc_frame,ffc_frame,release_frame,labeler,bowler_id\n",
        encoding="utf-8",
    )
    with pytest.raises(AnnotationError, match="duplicate column"):
        read_phase_labels(path)


def test_extra_fields_on_a_data_row_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text(HEADER + "\nB01,D01,10,20,30,SS,ok,leftover\n", encoding="utf-8")
    with pytest.raises(AnnotationError, match="unexpected extra fields"):
        read_phase_labels(path)


def test_header_names_are_stripped(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    padded = ",".join(f" {name} " for name in PHASE_LABEL_FIELDNAMES)
    path.write_text(padded + "\nB01,D01,10,20,30,SS,\n", encoding="utf-8")
    (label,) = read_phase_labels(path)
    assert label.key == ("B01", "D01")
    assert label.bfc_frame == 10


def test_blank_data_rows_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text(HEADER + "\n,,,,,,\nB01,D01,10,20,30,SS,\n", encoding="utf-8")
    assert read_phase_labels(path) == (_label(),)


def test_unclosed_quote_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "phase_labels.csv"
    path.write_text(HEADER + '\nB01,D01,10,20,30,SS,"unclosed\n', encoding="utf-8")
    with pytest.raises(AnnotationError, match="not a valid CSV"):
        read_phase_labels(path)
