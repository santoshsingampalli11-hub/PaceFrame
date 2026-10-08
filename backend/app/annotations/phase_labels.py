"""Read and write manual phase-label CSV files.

The on-disk schema matches ``fast_bowling_dataset/phase_labels/phase_labels.csv``.
This module does not open videos, run pose estimation, or detect phases.
"""

from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from app.annotations.models import (
    PHASE_LABEL_FIELDNAMES,
    AnnotationError,
    PhaseLabel,
)

_EXTRA_FIELDS = "_extra"


class _StrictCsv(csv.excel):
    strict = True


def read_phase_labels(path: str | Path) -> tuple[PhaseLabel, ...]:
    """Return labels from a UTF-8 CSV, in file order.

    Blank phase cells become ``None``. Duplicate ``(bowler_id, delivery_id)``
    rows raise ``AnnotationError``. Extra or missing columns are rejected.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Phase label file not found: {csv_path.name}")
    if not csv_path.is_file():
        raise AnnotationError(f"{csv_path.name} is not a file.")

    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, restkey=_EXTRA_FIELDS, dialect=_StrictCsv)
            _require_header(reader.fieldnames, csv_path.name)
            labels = tuple(
                _label_from_row(row, index)
                for index, row in enumerate(reader, start=2)
                if not _is_blank_row(row)
            )
    except UnicodeDecodeError as error:
        raise AnnotationError(f"{csv_path.name} is not valid UTF-8.") from error
    except csv.Error as error:
        raise AnnotationError(f"{csv_path.name} is not a valid CSV file.") from error
    except OSError as error:
        raise AnnotationError(f"Could not read {csv_path.name}.") from error

    _require_unique_keys(labels)
    return labels


def write_phase_labels(path: str | Path, labels: Sequence[PhaseLabel]) -> None:
    """Write ``labels`` as UTF-8 CSV using the dataset header, atomically.

    ``None`` phase frames become empty cells. Parent directories are created
    if missing. The destination is replaced only after the temporary file is
    fully written.
    """
    _require_unique_keys(labels)
    csv_path = Path(path)
    temp_path: Path | None = None
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f"{csv_path.name}.",
            suffix=".tmp",
            dir=csv_path.parent,
        )
        temp_path = Path(temp_name)
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(PHASE_LABEL_FIELDNAMES))
            writer.writeheader()
            for label in labels:
                writer.writerow(_row_from_label(label))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, csv_path)
        temp_path = None
    except OSError as error:
        raise AnnotationError(f"Could not write {csv_path.name}.") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def upsert_phase_label(labels: Sequence[PhaseLabel], annotation: PhaseLabel) -> tuple[PhaseLabel, ...]:
    """Return a new sequence with ``annotation`` added or replacing the same key.

    Existing order is kept. A new key is appended. Input sequences with
    duplicate keys are rejected.
    """
    _require_unique_keys(labels)
    updated = list(labels)
    for index, existing in enumerate(updated):
        if existing.key == annotation.key:
            updated[index] = annotation
            return tuple(updated)
    updated.append(annotation)
    return tuple(updated)


def upsert_phase_label_file(path: str | Path, annotation: PhaseLabel) -> tuple[PhaseLabel, ...]:
    """Add or replace one delivery in the CSV, creating the file if needed."""
    csv_path = Path(path)
    existing: tuple[PhaseLabel, ...] = ()
    if csv_path.exists():
        existing = read_phase_labels(csv_path)
    updated = upsert_phase_label(existing, annotation)
    write_phase_labels(csv_path, updated)
    return updated


def _require_header(fieldnames: list[str] | None, filename: str) -> None:
    if not fieldnames:
        raise AnnotationError(f"{filename} has no CSV header.")
    present = [(name or "").strip() for name in fieldnames]
    fieldnames[:] = present
    if any(not name for name in present):
        raise AnnotationError(f"{filename} header has an empty column name.")
    if len(present) != len(set(present)):
        raise AnnotationError(f"{filename} header has duplicate column names.")
    missing = [name for name in PHASE_LABEL_FIELDNAMES if name not in present]
    extra = [name for name in present if name not in PHASE_LABEL_FIELDNAMES]
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing columns {missing}")
        if extra:
            details.append(f"unexpected columns {extra}")
        raise AnnotationError(f"{filename} header is invalid: {'; '.join(details)}.")


def _is_blank_row(row: dict[str, str | None | list[str]]) -> bool:
    extra = row.get(_EXTRA_FIELDS)
    if extra:
        return False
    return not any(str(value).strip() for name, value in row.items() if name != _EXTRA_FIELDS and value)


def _label_from_row(row: dict[str, str | None | list[str]], line_number: int) -> PhaseLabel:
    row_desc = f"row {line_number}"
    extra = row.get(_EXTRA_FIELDS)
    if extra:
        raise AnnotationError(f"{row_desc}: unexpected extra fields.")
    try:
        return PhaseLabel(
            bowler_id=_cell(row, "bowler_id"),
            delivery_id=_cell(row, "delivery_id"),
            bfc_frame=_parse_frame_cell("BFC", _cell(row, "bfc_frame")),
            ffc_frame=_parse_frame_cell("FFC", _cell(row, "ffc_frame")),
            release_frame=_parse_frame_cell("Release", _cell(row, "release_frame")),
            labeler=_cell(row, "labeler"),
            notes=_cell(row, "notes"),
        )
    except AnnotationError as error:
        raise AnnotationError(f"{row_desc}: {error}") from error


def _cell(row: dict[str, str | None], name: str) -> str:
    value = row.get(name)
    return "" if value is None else value


def _parse_frame_cell(display: str, raw: str) -> int | None:
    text = raw.strip()
    if text == "":
        return None
    if not (text.isascii() and text.isdecimal()):
        raise AnnotationError(f"{display} frame is not a non-negative integer, got {text!r}.")
    return int(text)


def _row_from_label(label: PhaseLabel) -> dict[str, str]:
    return {
        "bowler_id": label.bowler_id,
        "delivery_id": label.delivery_id,
        "bfc_frame": _frame_cell(label.bfc_frame),
        "ffc_frame": _frame_cell(label.ffc_frame),
        "release_frame": _frame_cell(label.release_frame),
        "labeler": label.labeler,
        "notes": label.notes,
    }


def _frame_cell(value: int | None) -> str:
    return "" if value is None else str(value)


def _require_unique_keys(labels: Sequence[PhaseLabel]) -> None:
    seen: dict[tuple[str, str], int] = {}
    for label in labels:
        if label.key in seen:
            bowler_id, delivery_id = label.key
            raise AnnotationError(
                f"Duplicate phase label for bowler_id={bowler_id!r}, delivery_id={delivery_id!r}."
            )
        seen[label.key] = 1
