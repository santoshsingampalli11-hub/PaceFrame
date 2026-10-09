"""Optional click positions for manual BFC / FFC / release markers.

This file is not the canonical phase-label CSV. It only stores where the
annotator clicked on a real frame. A row is meaningful together with the
matching event frame in ``phase_labels.csv``.
"""

from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.annotations.models import AnnotationError

MARKER_FIELDNAMES: tuple[str, ...] = (
    "bowler_id",
    "delivery_id",
    "event",
    "frame_index",
    "x_normalized",
    "y_normalized",
)

MARKER_EVENTS: tuple[str, ...] = ("bfc", "ffc", "release")

_EXTRA_FIELDS = "_extra"


class _StrictCsv(csv.excel):
    strict = True


@dataclass(frozen=True)
class MarkerPosition:
    """One manual click on the original image, not a measured body point."""

    bowler_id: str
    delivery_id: str
    event: str
    frame_index: int
    x_normalized: float
    y_normalized: float

    def __post_init__(self) -> None:
        if not str(self.bowler_id).strip() or not str(self.delivery_id).strip():
            raise AnnotationError("Marker bowler_id and delivery_id must not be empty.")
        if self.event not in MARKER_EVENTS:
            raise AnnotationError(f"Unknown marker event {self.event!r}.")
        if isinstance(self.frame_index, bool) or not isinstance(self.frame_index, int):
            raise AnnotationError(f"Marker frame must be an integer, got {self.frame_index!r}.")
        if self.frame_index < 0:
            raise AnnotationError(f"Marker frame must be >= 0, got {self.frame_index}.")
        for name, value in (("x_normalized", self.x_normalized), ("y_normalized", self.y_normalized)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AnnotationError(f"Marker {name} must be a real number, got {value!r}.")
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")):
                raise AnnotationError(f"Marker {name} must be finite, got {value!r}.")
            if not 0.0 <= number <= 1.0:
                raise AnnotationError(f"Marker {name} must be inside 0..1, got {number}.")
            object.__setattr__(self, name, number)

    @property
    def key(self) -> tuple[str, str, str]:
        return self.bowler_id, self.delivery_id, self.event


def read_marker_positions(path: str | Path) -> tuple[MarkerPosition, ...]:
    """Read marker rows in file order. Duplicate keys are an error."""
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Marker file not found: {csv_path.name}")
    if not csv_path.is_file():
        raise AnnotationError(f"{csv_path.name} is not a file.")
    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, restkey=_EXTRA_FIELDS, dialect=_StrictCsv)
            _require_header(reader.fieldnames, csv_path.name)
            markers = tuple(
                _marker_from_row(row, index)
                for index, row in enumerate(reader, start=2)
                if not _is_blank_row(row)
            )
    except UnicodeDecodeError as error:
        raise AnnotationError(f"{csv_path.name} is not valid UTF-8.") from error
    except csv.Error as error:
        raise AnnotationError(f"{csv_path.name} is not a valid CSV file.") from error
    except OSError as error:
        raise AnnotationError(f"Could not read {csv_path.name}.") from error
    _require_unique(markers)
    return markers


def write_marker_positions(path: str | Path, markers: Sequence[MarkerPosition]) -> None:
    """Atomically write marker rows. Does not touch videos or phase-label files."""
    _require_unique(markers)
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
            writer = csv.DictWriter(output, fieldnames=list(MARKER_FIELDNAMES))
            writer.writeheader()
            for marker in markers:
                writer.writerow(_row_from_marker(marker))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, csv_path)
        temp_path = None
    except OSError as error:
        raise AnnotationError(f"Could not write {csv_path.name}.") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def replace_delivery_markers(
    path: str | Path,
    bowler_id: str,
    delivery_id: str,
    markers: Sequence[MarkerPosition],
) -> tuple[MarkerPosition, ...]:
    """Replace one delivery's marker rows and keep every other delivery."""
    for marker in markers:
        if (marker.bowler_id, marker.delivery_id) != (bowler_id, delivery_id):
            raise AnnotationError("Marker rows do not match the delivery being saved.")
    csv_path = Path(path)
    existing: tuple[MarkerPosition, ...] = ()
    if csv_path.exists():
        existing = read_marker_positions(csv_path)
    kept = [
        marker
        for marker in existing
        if (marker.bowler_id, marker.delivery_id) != (bowler_id, delivery_id)
    ]
    updated = tuple(kept) + tuple(markers)
    write_marker_positions(csv_path, updated)
    return updated


def _require_header(fieldnames: list[str] | None, filename: str) -> None:
    if not fieldnames:
        raise AnnotationError(f"{filename} has no CSV header.")
    present = [(name or "").strip() for name in fieldnames]
    fieldnames[:] = present
    if any(not name for name in present) or len(present) != len(set(present)):
        raise AnnotationError(f"{filename} header is invalid.")
    missing = [name for name in MARKER_FIELDNAMES if name not in present]
    extra = [name for name in present if name not in MARKER_FIELDNAMES]
    if missing or extra:
        raise AnnotationError(f"{filename} header is invalid.")


def _is_blank_row(row: dict[str, str | None | list[str]]) -> bool:
    if row.get(_EXTRA_FIELDS):
        return False
    return not any(str(value).strip() for name, value in row.items() if name != _EXTRA_FIELDS and value)


def _marker_from_row(row: dict[str, str | None | list[str]], line_number: int) -> MarkerPosition:
    if row.get(_EXTRA_FIELDS):
        raise AnnotationError(f"row {line_number}: unexpected extra fields.")
    try:
        frame_text = _cell(row, "frame_index").strip()
        if not (frame_text.isascii() and frame_text.isdecimal()):
            raise AnnotationError(f"frame_index is not a non-negative integer, got {frame_text!r}.")
        return MarkerPosition(
            bowler_id=_cell(row, "bowler_id").strip(),
            delivery_id=_cell(row, "delivery_id").strip(),
            event=_cell(row, "event").strip(),
            frame_index=int(frame_text),
            x_normalized=_finite_unit(_cell(row, "x_normalized")),
            y_normalized=_finite_unit(_cell(row, "y_normalized")),
        )
    except AnnotationError as error:
        raise AnnotationError(f"row {line_number}: {error}") from error


def _cell(row: dict[str, str | None | list[str]], name: str) -> str:
    value = row.get(name)
    if isinstance(value, list):
        raise AnnotationError("unexpected extra fields.")
    return "" if value is None else value


def _finite_unit(raw: str) -> float:
    text = raw.strip()
    try:
        value = float(text)
    except ValueError as error:
        raise AnnotationError(f"normalized coordinate is not a number, got {text!r}.") from error
    if value != value or value in (float("inf"), float("-inf")):
        raise AnnotationError(f"normalized coordinate must be finite, got {text!r}.")
    return value


def _row_from_marker(marker: MarkerPosition) -> dict[str, str]:
    return {
        "bowler_id": marker.bowler_id,
        "delivery_id": marker.delivery_id,
        "event": marker.event,
        "frame_index": str(marker.frame_index),
        "x_normalized": f"{marker.x_normalized:.8f}",
        "y_normalized": f"{marker.y_normalized:.8f}",
    }


def _require_unique(markers: Sequence[MarkerPosition]) -> None:
    seen: set[tuple[str, str, str]] = set()
    for marker in markers:
        if marker.key in seen:
            raise AnnotationError(
                f"Duplicate marker for bowler_id={marker.bowler_id!r}, "
                f"delivery_id={marker.delivery_id!r}, event={marker.event!r}."
            )
        seen.add(marker.key)
