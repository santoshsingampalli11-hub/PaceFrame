"""Remember which video file a delivery's manual labels were saved for.

The phase-label CSV stays unchanged. This side file stores only the video
file name, not a full path. It does not prove the frames are correct.
"""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

from app.annotations.models import AnnotationError

VIDEO_IDENTITY_FIELDNAMES: tuple[str, ...] = (
    "bowler_id",
    "delivery_id",
    "video_filename",
)


def video_identity_path(labels_path: str | Path) -> Path:
    labels = Path(labels_path)
    return labels.with_name(labels.name + ".videos.csv")


def lookup_video_filename(
    labels_path: str | Path,
    bowler_id: str,
    delivery_id: str,
) -> str | None:
    """Return the saved video file name for this delivery, if one was stored."""
    path = video_identity_path(labels_path)
    if not path.exists():
        return None
    matches = [
        row[2]
        for row in _read_rows(path)
        if row[0] == bowler_id and row[1] == delivery_id
    ]
    if not matches:
        return None
    if len(set(matches)) > 1:
        raise AnnotationError(
            f"More than one video name is stored for {bowler_id}/{delivery_id}."
        )
    return matches[0]


def remember_video_filename(
    labels_path: str | Path,
    bowler_id: str,
    delivery_id: str,
    video_filename: str,
) -> None:
    """Record that this delivery's labels belong to ``video_filename``."""
    name = Path(video_filename).name
    if not name or name in {".", ".."} or name != video_filename.replace("\\", "/").split("/")[-1]:
        raise AnnotationError("Video identity must be a file name, not a path.")
    path = video_identity_path(labels_path)
    rows = _read_rows(path) if path.exists() else []
    kept = [row for row in rows if not (row[0] == bowler_id and row[1] == delivery_id)]
    kept.append((bowler_id, delivery_id, name))
    _write_rows(path, kept)


def _read_rows(path: Path) -> list[tuple[str, str, str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise AnnotationError(f"{path.name} has no CSV header.")
            present = [(name or "").strip() for name in reader.fieldnames]
            if present != list(VIDEO_IDENTITY_FIELDNAMES):
                raise AnnotationError(f"{path.name} header is invalid.")
            rows: list[tuple[str, str, str]] = []
            for row in reader:
                if not any((value or "").strip() for value in row.values()):
                    continue
                rows.append(
                    (
                        (row.get("bowler_id") or "").strip(),
                        (row.get("delivery_id") or "").strip(),
                        Path((row.get("video_filename") or "").strip()).name,
                    )
                )
    except UnicodeDecodeError as error:
        raise AnnotationError(f"{path.name} is not valid UTF-8.") from error
    except OSError as error:
        raise AnnotationError(f"Could not read {path.name}.") from error
    return rows


def _write_rows(path: Path, rows: list[tuple[str, str, str]]) -> None:
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(VIDEO_IDENTITY_FIELDNAMES))
            writer.writeheader()
            for bowler_id, delivery_id, video_filename in rows:
                writer.writerow(
                    {
                        "bowler_id": bowler_id,
                        "delivery_id": delivery_id,
                        "video_filename": video_filename,
                    }
                )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, path)
        temp_path = None
    except OSError as error:
        raise AnnotationError(f"Could not write {path.name}.") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
