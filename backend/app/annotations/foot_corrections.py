"""Manual corrections for six foot landmarks. Raw pose output is not changed.

LEFT and RIGHT are the athlete's own sides, not the left and right of the
picture. A correction is a human click. It is not proof of anatomical truth,
and it is not a BFC, FFC, or release mark.
"""

from __future__ import annotations

import csv
import hashlib
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.biomechanics.geometry import Point2D, distance
from app.pose.landmarks import PoseFrame

FOOT_LANDMARKS: tuple[str, ...] = (
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
)

FOOT_LABELS: dict[str, str] = {
    "left_ankle": "L-ankle",
    "right_ankle": "R-ankle",
    "left_heel": "L-heel",
    "right_heel": "R-heel",
    "left_foot_index": "L-foot",
    "right_foot_index": "R-foot",
}

FOOT_CORRECTION_FIELDNAMES: tuple[str, ...] = (
    "video_sha256",
    "bowler_id",
    "delivery_id",
    "frame_index",
    "landmark_name",
    "x_normalized",
    "y_normalized",
    "correction_source",
)

_MANUAL = "manual"


class FootCorrectionError(ValueError):
    """A manual foot correction cannot be stored or read."""


@dataclass(frozen=True)
class FootCorrection:
    """One human click for one foot landmark on one decoded frame."""

    video_sha256: str
    bowler_id: str
    delivery_id: str
    frame_index: int
    landmark_name: str
    x_normalized: float
    y_normalized: float
    correction_source: str = _MANUAL

    def __post_init__(self) -> None:
        if not self.video_sha256 or len(self.video_sha256) != 64:
            raise FootCorrectionError("video_sha256 must be a SHA-256 hex digest.")
        if not self.bowler_id.strip() or not self.delivery_id.strip():
            raise FootCorrectionError("bowler_id and delivery_id must not be empty.")
        if self.landmark_name not in FOOT_LANDMARKS:
            raise FootCorrectionError(f"Unsupported foot landmark {self.landmark_name!r}.")
        if isinstance(self.frame_index, bool) or not isinstance(self.frame_index, int) or self.frame_index < 0:
            raise FootCorrectionError(f"Frame index must be an integer >= 0, got {self.frame_index!r}.")
        if self.correction_source != _MANUAL:
            raise FootCorrectionError("correction_source must be 'manual'.")
        for name, value in (("x_normalized", self.x_normalized), ("y_normalized", self.y_normalized)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise FootCorrectionError(f"{name} must be a real number.")
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")) or not 0.0 <= number <= 1.0:
                raise FootCorrectionError(f"{name} must be finite and inside 0..1, got {value!r}.")
            object.__setattr__(self, name, number)

    @property
    def key(self) -> tuple[str, str, str, int, str]:
        return (
            self.video_sha256,
            self.bowler_id,
            self.delivery_id,
            self.frame_index,
            self.landmark_name,
        )


def file_sha256(path: str | Path) -> str:
    """Hash a file once. Callers should keep the result for the session."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def consecutive_foot_shift(
    previous: PoseFrame | None,
    current: PoseFrame | None,
    landmark_name: str,
) -> float | None:
    """Normalized image distance of one raw foot point between two frames.

    The value is a description of the raw prediction. It is not a tracking
    error, a quality score, or a decision to correct the point. ``None`` means
    one of the frames has no raw point, so nothing is interpolated.
    """
    if landmark_name not in FOOT_LANDMARKS:
        raise FootCorrectionError(f"Unsupported foot landmark {landmark_name!r}.")
    if previous is None or current is None:
        return None
    if abs(current.frame_index - previous.frame_index) != 1:
        return None
    if landmark_name not in previous.landmarks or landmark_name not in current.landmarks:
        return None
    before = previous.landmarks[landmark_name]
    after = current.landmarks[landmark_name]
    return distance(Point2D(before.x, before.y), Point2D(after.x, after.y))


def choose_foot_point(
    raw: tuple[float, float] | None,
    correction: tuple[float, float] | None,
    *,
    use_correction: bool,
) -> tuple[float, float] | None:
    """Return the requested point. Raw and manual values are never blended."""
    if use_correction:
        return correction
    return raw


class FootReview:
    """Corrections for one delivery of one video. The raw pose is not stored here."""

    def __init__(self, video_sha256: str, bowler_id: str, delivery_id: str) -> None:
        self.video_sha256 = video_sha256
        self.bowler_id = bowler_id
        self.delivery_id = delivery_id
        self.items: dict[tuple[int, str], FootCorrection] = {}
        self.index = 0
        self.active = False
        self.show_raw = True
        self.show_corrected = True
        self.dirty = False

    def selected(self) -> str:
        return FOOT_LANDMARKS[self.index]

    def cycle(self, step: int = 1) -> str:
        self.active = True
        self.index = (self.index + step) % len(FOOT_LANDMARKS)
        return self.selected()

    def place(self, frame_index: int, x_normalized: float, y_normalized: float) -> FootCorrection:
        item = FootCorrection(
            video_sha256=self.video_sha256,
            bowler_id=self.bowler_id,
            delivery_id=self.delivery_id,
            frame_index=frame_index,
            landmark_name=self.selected(),
            x_normalized=x_normalized,
            y_normalized=y_normalized,
        )
        self.items[(frame_index, item.landmark_name)] = item
        self.dirty = True
        return item

    def clear_selected(self, frame_index: int) -> bool:
        key = (frame_index, self.selected())
        if key not in self.items:
            return False
        del self.items[key]
        self.dirty = True
        return True

    def on_frame(self, frame_index: int) -> dict[str, tuple[float, float]]:
        return {
            name: (item.x_normalized, item.y_normalized)
            for (index, name), item in self.items.items()
            if index == frame_index
        }


def read_foot_corrections(path: str | Path) -> tuple[FootCorrection, ...]:
    csv_path = Path(path)
    if not csv_path.is_file():
        raise FootCorrectionError(f"Foot correction file not found: {csv_path.name}")
    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if list(reader.fieldnames or []) != list(FOOT_CORRECTION_FIELDNAMES):
                raise FootCorrectionError(f"{csv_path.name} header is invalid.")
            rows = []
            for line_number, row in enumerate(reader, start=2):
                if not any((value or "").strip() for value in row.values()):
                    continue
                try:
                    rows.append(_from_row(row))
                except FootCorrectionError as error:
                    raise FootCorrectionError(f"row {line_number}: {error}") from error
    except UnicodeDecodeError as error:
        raise FootCorrectionError(f"{csv_path.name} is not valid UTF-8.") from error
    except OSError as error:
        raise FootCorrectionError(f"Could not read {csv_path.name}.") from error
    _require_unique(rows)
    return tuple(rows)


def load_foot_corrections(
    path: str | Path,
    video_sha256: str,
    bowler_id: str,
    delivery_id: str,
) -> tuple[tuple[FootCorrection, ...], list[str]]:
    """Load only corrections for this video hash and delivery.

    Rows for another hash are left on disk and are not returned.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        return (), []
    rows = read_foot_corrections(csv_path)
    matched = []
    other_hash = 0
    warnings: list[str] = []
    for row in rows:
        if row.video_sha256 != video_sha256:
            other_hash += 1
            continue
        if (row.bowler_id, row.delivery_id) == (bowler_id, delivery_id):
            matched.append(row)
    if other_hash:
        warnings.append(
            f"{other_hash} foot corrections belong to another video and were not loaded."
        )
    return tuple(matched), warnings


def write_foot_corrections(path: str | Path, rows: Sequence[FootCorrection]) -> None:
    _require_unique(rows)
    csv_path = Path(path)
    temp_path: Path | None = None
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=f"{csv_path.name}.", suffix=".tmp", dir=csv_path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(FOOT_CORRECTION_FIELDNAMES))
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "video_sha256": row.video_sha256,
                        "bowler_id": row.bowler_id,
                        "delivery_id": row.delivery_id,
                        "frame_index": str(row.frame_index),
                        "landmark_name": row.landmark_name,
                        "x_normalized": f"{row.x_normalized:.8f}",
                        "y_normalized": f"{row.y_normalized:.8f}",
                        "correction_source": row.correction_source,
                    }
                )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, csv_path)
        temp_path = None
    except OSError as error:
        raise FootCorrectionError(f"Could not write {csv_path.name}.") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def replace_delivery_foot_corrections(
    path: str | Path,
    video_sha256: str,
    bowler_id: str,
    delivery_id: str,
    rows: Sequence[FootCorrection],
) -> tuple[FootCorrection, ...]:
    """Replace one delivery's corrections and keep every other video and delivery."""
    for row in rows:
        if (row.video_sha256, row.bowler_id, row.delivery_id) != (video_sha256, bowler_id, delivery_id):
            raise FootCorrectionError("Foot correction does not match the video and delivery being saved.")
    csv_path = Path(path)
    existing: tuple[FootCorrection, ...] = ()
    if csv_path.exists():
        existing = read_foot_corrections(csv_path)
    kept = [
        row
        for row in existing
        if (row.video_sha256, row.bowler_id, row.delivery_id) != (video_sha256, bowler_id, delivery_id)
    ]
    updated = tuple(kept) + tuple(rows)
    write_foot_corrections(csv_path, updated)
    return updated


def _from_row(row: dict[str, str | None]) -> FootCorrection:
    frame_text = (row.get("frame_index") or "").strip()
    if not (frame_text.isascii() and frame_text.isdecimal()):
        raise FootCorrectionError(f"frame_index is not a non-negative integer, got {frame_text!r}.")
    try:
        x_value = float((row.get("x_normalized") or "").strip())
        y_value = float((row.get("y_normalized") or "").strip())
    except ValueError as error:
        raise FootCorrectionError("normalized coordinate is not a number.") from error
    return FootCorrection(
        video_sha256=(row.get("video_sha256") or "").strip(),
        bowler_id=(row.get("bowler_id") or "").strip(),
        delivery_id=(row.get("delivery_id") or "").strip(),
        frame_index=int(frame_text),
        landmark_name=(row.get("landmark_name") or "").strip(),
        x_normalized=x_value,
        y_normalized=y_value,
        correction_source=(row.get("correction_source") or "").strip(),
    )


def _require_unique(rows: Sequence[FootCorrection]) -> None:
    seen: set[tuple[str, str, str, int, str]] = set()
    for row in rows:
        if row.key in seen:
            raise FootCorrectionError(
                f"Duplicate foot correction for frame {row.frame_index} {row.landmark_name}."
            )
        seen.add(row.key)
