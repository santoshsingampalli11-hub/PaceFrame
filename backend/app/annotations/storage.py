"""Load and save one delivery's manual labels.

Phase frames go to the existing phase-label CSV. Click positions go to a
separate marker file. Neither function opens a video.
"""

from __future__ import annotations

from pathlib import Path

from app.annotations.marker_sidecar import read_marker_positions, replace_delivery_markers
from app.annotations.models import AnnotationError
from app.annotations.phase_labels import read_phase_labels, upsert_phase_label_file
from app.annotations.video_identity import remember_video_filename


def load_delivery(
    session: DeliveryAnnotation,
    labels_path: str | Path,
    markers_path: str | Path,
) -> list[str]:
    """Fill ``session`` from disk. Mismatched clicks are skipped, not guessed.

    Returns warnings. Does not mark the session dirty.
    """
    warnings: list[str] = []
    labels_file = Path(labels_path)
    if labels_file.exists():
        for label in read_phase_labels(labels_file):
            if label.key != session.key:
                continue
            session.bfc_frame = label.bfc_frame
            session.ffc_frame = label.ffc_frame
            session.release_frame = label.release_frame
            session.labeler = label.labeler
            session.notes = label.notes
            break

    markers_file = Path(markers_path)
    if markers_file.exists():
        for marker in read_marker_positions(markers_file):
            if (marker.bowler_id, marker.delivery_id) != session.key:
                continue
            expected = session.frame_for(marker.event)
            if expected != marker.frame_index:
                warnings.append(
                    f"Ignored {marker.event} click on frame {marker.frame_index}; "
                    f"the saved event frame is {expected!r}."
                )
                continue
            session.markers[marker.event] = marker

    session.dirty = False
    return warnings


def save_delivery(
    session: DeliveryAnnotation,
    labels_path: str | Path,
    markers_path: str | Path,
    video_filename: str | None = None,
) -> None:
    """Write this delivery after the caller has confirmed.

    Other deliveries already in either file are kept. The phase-label file is
    written first. If the marker file then fails, the session stays dirty.
    When ``video_filename`` is given, only the file name is stored beside the
    labels so a later open of a different video is not treated as the same one.
    """
    label = session.to_phase_label()
    upsert_phase_label_file(labels_path, label)
    try:
        replace_delivery_markers(
            markers_path,
            session.bowler_id,
            session.delivery_id,
            session.marker_rows(),
        )
        if video_filename is not None:
            remember_video_filename(
                labels_path,
                session.bowler_id,
                session.delivery_id,
                video_filename,
            )
    except Exception as error:
        session.dirty = True
        raise AnnotationError(
            "Phase frames were written, but the marker file or video name was not. "
            "This delivery is still unsaved. "
            f"{error}"
        ) from error
    session.dirty = False
