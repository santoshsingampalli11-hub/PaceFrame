# Evaluation metrics

These definitions are for use after independent references exist. The CSV templates in this folder are headers only. Do not calculate an accuracy number from engineering clips, from the analyzer's own labels, or from MediaPipe points used as their own reference.

A missing value stays blank. It is not zero degrees and not a zero-frame error.

## Sets

Keep these apart:

- `engineering`: software clips, including `raw_videos/stress_tests/`. Not an evaluation result.
- `evaluation`: participant recordings made under `RECORDING_GUIDE.md`, with the system's saved human event frames.
- `independent_review`: a second person's event frames or pixel reference, stored in the independent sheets and not written over the system's labels.

`evaluation_inventory.csv` uses `set_role` for that separation. Do not put an engineering file on an evaluation row.

## Pose and measurement availability

For each evaluation delivery, read the stored measurement for FFC and for Release.

- Available: `status` is `available` and `angle_degrees` is a finite number from 0 to 180.
- Unavailable: `status` is `unavailable`, or the angle is null. Report the stored reason. Do not replace it with 0.

Report the count available and the count unavailable for FFC, for Release, and for deliveries where both are available. The denominator is the number of evaluation deliveries in the inventory, not the number of engineering clips.

`review_status` and visibility scores are not accuracy.

## Event-frame disagreement

Compare the system's saved frame index with `independent_event_frames.csv` for the same `bowler_id`, `delivery_id`, and `video_sha256`.

Disagreement, in frames, is:

`independent_frame_index - system_frame_index`

Calculate it only when both indexes are present integers greater than or equal to 0. If either side is blank, the disagreement is blank.

BFC may be blank on either side. Do not invent it. FFC must be earlier than Release on each sheet separately. Do not reorder indexes to force that.

This is not the same object as an angle error. The existing helper `compare_reference_frame` reports candidate minus reference when both exist, and it leaves the error empty when either frame is missing.

## Angle error

Compare an automatic angle with `independent_reference_angles.csv` only when all of these match:

- bowler id
- delivery id
- video SHA-256
- phase (`FFC` or `Release`)
- zero-based frame index
- anatomical front leg

Signed error, in degrees, is automatic angle minus reference angle. Absolute error is the absolute value of that signed error. This is the same sign as `compare_front_knee_angle`.

Do not compare across different frames. Do not compare a left-leg measurement with a right-leg reference. If the automatic result is unavailable, or the reference angle is blank, the error cells stay blank and the row status records why.

## Mean absolute error

Mean absolute error is the mean of the absolute errors among rows that were actually compared.

Keep FFC and Release separate. Also report how many rows were excluded because the reference was missing, the measurement was unavailable, the identity did not match, or the same identity appeared more than once.

`summarise_angle_comparisons` already does this count. When no pair is compared, its mean is null, not zero. Duplicate identities are left out of the mean rather than averaged together.

Do not report a mean until at least one independent reference pair exists.

## Per-delivery error table

`evaluation_errors.csv` is the header for that table. One row per bowler, delivery, and phase. Leave the file header-only until the references exist.

`status` uses the comparison outcome, such as compared, reference missing, measurement unavailable, or mismatch. It is not a technique grade.

## Units

Angles are decimal degrees. Frame indexes are zero-based decoded frames. Disagreement is a frame count, not a time in seconds. Encoded FPS is not used to turn a frame gap into a scientific time.
