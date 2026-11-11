# Checklist for the first evaluation recordings

This list is the gate before a delivery is treated as evaluation material. It does not produce an accuracy result. Software steps that already exist are in `../PILOT_CHECKLIST.md`.

Do not fill `evaluation_errors.csv` from this checklist. Do not add rows for `raw_videos/stress_tests/`.

## Before recording

- The participant has been told what the video is for and has agreed.
- The place is clear of people and objects in the ball's path.
- The phone is fixed, landscape, and side-on, as in `RECORDING_GUIDE.md`.
- No required camera distance has been invented. A measured distance, if any, will go in the notes.
- Anonymous ids are chosen and do not contain a name.

## After each delivery

- The original file is stored unchanged.
- Inspection has been run. Encoded FPS and decoded frame count in `evaluation_inventory.csv` come from that inspection.
- `video_sha256` is the hash of that same file.
- `set_role` is `evaluation`.
- A person has looked at the video and recorded `camera_view_confirmed` and `full_body_visibility_confirmed` as yes or no. Leaving them blank means the check was not done. Do not mark yes from the file metadata.
- FFC and Release frame indexes are zero-based decoded frames. BFC may be blank.
- FFC is an earlier frame than Release. The indexes were not reordered.
- `reviewer_id` is set. Notes do not include a person's name.
- The system's saved labels are not edited to match a later reviewer.

## Independent review, when a second person is available

- Event frames go in `independent_event_frames.csv`, not into the system's label file.
- Hip, knee, and ankle pixels go in `independent_reference_angles.csv`, using `REFERENCE_ANNOTATION.md`.
- Those points are clicked on the decoded image. They are not copied from MediaPipe.
- The reference row names the same SHA-256 and the same frame index that was viewed.
- Ambiguous joints are left blank, not set to zero.

## Stop

Stop before any accuracy statement if any of these is true:

- The video was cropped, filtered, or re-encoded.
- The evaluation row shares an id or a file with an engineering clip.
- The reference angle was copied from the analyzer.
- An unavailable angle or a missing frame was stored as 0.
- The only labels are the same labels the measurement already used.
