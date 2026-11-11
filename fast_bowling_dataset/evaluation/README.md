# Evaluation preparation

This folder is the written protocol for a later scientific check of the existing semi-automatic 2D analyzer. It does not contain videos, labels, coordinates, or angles.

The analyzer does not detect bowling events. A person chooses the frames. The knee number is the unsigned image-plane angle at the hip, knee, and ankle on those frames. It is not a 3D laboratory angle, not a technique score, and not an injury estimate.

| Document | Use |
| --- | --- |
| `RECORDING_GUIDE.md` | How to record a delivery for evaluation |
| `evaluation_inventory.csv` | Empty inventory of videos and human event frames |
| `independent_event_frames.csv` | Empty sheet for a second person's event frames |
| `REFERENCE_ANNOTATION.md` | How to mark hip, knee, and ankle in pixels |
| `independent_reference_angles.csv` | Empty sheet for those pixel marks and the reference angle |
| `METRICS.md` | What may be calculated after independent references exist |
| `evaluation_errors.csv` | Empty error-table header. Do not fill it yet |
| `PILOT_CHECKLIST.md` | Gates before the first evaluation recordings are used |

Engineering clips under `raw_videos/stress_tests/` stay out of the evaluation set. The existing recording note is `../RECORDING_PROTOCOL.md`. The existing software checklist is `../PILOT_CHECKLIST.md`.
