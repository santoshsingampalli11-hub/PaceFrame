# Recording guide for evaluation deliveries

Use this with `../RECORDING_PROTOCOL.md`. A recording that follows both notes is still one 2D smartphone video. It is not laboratory motion capture, and it is not evidence that a later knee angle is accurate.

Do not set a required camera distance. If someone measures a distance on the day, write that number in the inventory notes. If it was not measured, leave the note blank.

## Camera

- Fix the phone on a tripod or another mount that does not move during the delivery.
- Record in landscape.
- Point the camera side-on to the run-up and the delivery stride.
- Keep the same mount, aim, and zoom for the deliveries that are meant to be compared, when the ground and the session allow it. If the setup changes, write what changed.
- Do not pan, tilt, or follow the bowler.
- Do not use digital zoom.
- Keep the whole delivery action in the frame, from the approach through ball release.
- Keep the whole bowler in the frame, including both shoes and the bowling hand.
- Avoid another person overlapping the bowler.

The file's encoded frame rate is the container rate reported by inspection. It is not a measured capture clock, and it is not proof of the time between frames.

## Original file

Keep the file that came off the phone. Do not crop, filter, stabilize, or re-encode it before inspection or measurement. The SHA-256 used later is the hash of that file.

## People and safety

- Use anonymous ids only: bowlers `B01`, `B02`, and deliveries `D01`, `D02`. Do not put a name in a filename, a CSV, or a note.
- Tell the participant what the video is for, that it stays on the project machine, and that the project is not a medical or injury assessment.
- Record only after the participant agrees. Stop and delete the file if they ask.
- Choose a place where the bowler can deliver without people, windows, or equipment in the ball's path.
- Stop if anyone walks into that path.
- Do not ask anyone to bowl through pain or through an unsafe surface.

## What this guide does not claim

A clear side-on picture does not confirm that the view is scientifically suitable. A decoded frame count does not confirm the capture clock. MediaPipe landmarks are not the independent reference described in `REFERENCE_ANNOTATION.md`.

Clips in `raw_videos/stress_tests/` are engineering footage. They are not evaluation recordings and not independently reviewed labels.
