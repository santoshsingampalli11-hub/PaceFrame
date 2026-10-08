"""Manual phase-label reference data. Independent of video, pose, and FastAPI.

Labels are annotator-selected BFC / FFC / release frames. Automatic phase
detection is not implemented here.
"""

from app.annotations.models import (
    PHASE_LABEL_FIELDNAMES,
    AnnotationError,
    PhaseLabel,
    validate_phase_labels,
)
from app.annotations.phase_labels import (
    read_phase_labels,
    upsert_phase_label,
    upsert_phase_label_file,
    write_phase_labels,
)

__all__ = [
    "PHASE_LABEL_FIELDNAMES",
    "AnnotationError",
    "PhaseLabel",
    "read_phase_labels",
    "upsert_phase_label",
    "upsert_phase_label_file",
    "validate_phase_labels",
    "write_phase_labels",
]
