# Fast Bowling V1 dataset

This folder holds **templates and rules** for the future V1 dataset. It does not contain videos, landmarks, phase labels, or measurements yet.

**Recommended location:** keep this folder in the project root. Put real videos only under `raw_videos/`. Those files are gitignored.

Do not put real names in filenames. Use anonymous IDs: bowlers `B01`, `B02`, … and deliveries `D01`, `D02`, …

## Layout

```text
fast_bowling_dataset/
├── raw_videos/          # B01/D01.mp4, …  (local only, not committed)
│   └── stress_tests/    # engineering clips only, not the V1 dataset
├── metadata/
│   └── bowlers.csv      # one row per delivery (header only until data is collected)
├── phase_labels/
│   └── phase_labels.csv # future manual BFC / FFC / release frames
├── landmarks/           # future per-delivery landmark CSVs
├── measurements/        # future biomechanical measurements (none yet)
└── validation/          # future manual vs automatic comparison (none yet)
```

## Metadata (`metadata/bowlers.csv`)

| Field | Meaning |
| --- | --- |
| `bowler_id` | Anonymous ID such as `B01` |
| `delivery_id` | Anonymous ID such as `D01` |
| `recording_date` | `YYYY-MM-DD` if known |
| `video_filename` | File name only, for example `D01.mp4` |
| `handedness` | `left`, `right`, or empty if not collected |
| `camera_fps` | Frame rate reported by the file |
| `resolution` | `widthxheight`, for example `1920x1080` |
| `camera_view` | Intended view, for example `side-on` |
| `camera_distance_m` | Distance in metres if recorded; otherwise empty |
| `calibration_available` | `yes` or `no` |
| `notes` | Free text. No personal names |

## Phase labels (`phase_labels/phase_labels.csv`)

Manual labels only. Automatic BFC / FFC / release detection is **not implemented**.

| Field | Meaning |
| --- | --- |
| `bowler_id` | Same ID as the metadata row |
| `delivery_id` | Same ID as the metadata row |
| `bfc_frame` | Frame index of back-foot contact, or empty |
| `ffc_frame` | Frame index of front-foot contact, or empty |
| `release_frame` | Frame index of ball release, or empty |
| `labeler` | Who labelled the frames (initials or role, not a full name) |
| `notes` | Free text |

Do not invent values for these columns.

Stress-test clips under `raw_videos/stress_tests/` are **engineering-only**. They are not participant data, not scientific validation, not training data, and not ground truth. The videos themselves stay gitignored; the folder README may be committed.

## Landmark export (`landmarks/Bxx_Dyy.csv`)

Future pose output should use this estimator-independent format. One row per landmark per frame.

| Field | Meaning |
| --- | --- |
| `bowler_id` | Anonymous bowler ID |
| `delivery_id` | Anonymous delivery ID |
| `frame_index` | 0-based frame index from the video reader |
| `timestamp_seconds` | `index / fps` from the video reader |
| `landmark_name` | Name from `LANDMARK_NAMES`, for example `left_knee` |
| `x_normalized` | Fraction of image width from the left edge |
| `y_normalized` | Fraction of image height from the top edge |
| `visibility` | Model visibility score, or empty |
| `presence` | Model presence score, or empty |

These coordinates are image estimates, not physical measurements.

## Measurements and validation

`measurements/biomechanical_measurements.csv` and `validation/manual_vs_automatic.csv` are empty templates. Phase 4 has not started. Do not add fabricated numbers.

Every future measurement must document: definition, formula, bowling phase, scientific justification, and validation method.

## Rules

- This is a 2D / single-camera smartphone dataset, not laboratory motion capture.
- Do not use the earlier run-up clip as validation, training data, or ground truth.
- Do not commit personal videos, names, or phone numbers.
- Standardized side-on videos belong in `raw_videos/` once they exist.
