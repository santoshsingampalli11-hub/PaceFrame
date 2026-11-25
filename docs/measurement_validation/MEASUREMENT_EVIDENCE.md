# Measurement evidence

This note describes the coordinates stored with a new 2D front-knee measurement. Storing them does not validate the angle.

## Schema

Available measurements include `calculation_evidence` with schema `front-knee-evidence-v1`.

The object records the confirmed front leg, the landmark names, the decoded frame index, the pose-frame timestamp, the frame width and height, and for the hip, knee, and ankle:

- normalized `x` and `y` from the pose estimator
- the pixel `x` and `y` passed into `angle_abc_degrees`
- visibility and presence when the model supplied them, otherwise null

The pixel values are `normalized_x * width` and `normalized_y * height`. They are not rounded. The origin is the top-left. Positive `x` is right. Positive `y` is down. The unit is image pixels.

The angle definition stored with the evidence is the unsigned interior hip–knee–ankle angle, vertex at the knee, from 0 to 180 degrees. The calculation id is `angle_abc_degrees`.

`video_sha256` on the evidence is the same hash as the measurement report. The angle function does not compute the hash.

The timestamp is the pose frame's `timestamp_seconds`. In the current reader that is the decoded index divided by the container frame rate. It is not a verified capture clock.

## Missing data

If the hip, knee, or ankle is missing, a coordinate is non-finite, the pose is missing, or the exact labeled frame is absent, the status stays `unavailable`, the angle stays null, and `calculation_evidence` is null. A neighboring frame is not used. No visibility cutoff was added.

## Older reports

Reports written before this field existed do not have `calculation_evidence`. They remain readable. Their coordinates are not reconstructed from the video and the measurement is not recalculated.

## Reconstruction

A later checker can read the three stored pixel points and call `angle_abc_degrees(hip, knee, ankle)`. That recomputation checks that the stored angle matches the stored pixels. It does not check that the pixels sit on the joint.
