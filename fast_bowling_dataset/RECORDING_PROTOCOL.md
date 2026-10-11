# Recording protocol for original side-on deliveries

This note is for collecting the first original smartphone videos. A file that follows this list is still a 2D recording. Inspection of its metadata does not show that the video is suitable for biomechanics, and it does not validate any measurement.

Do not invent a required camera distance. If a distance is measured on the day, write that number in the metadata notes. If it is not measured, leave it blank.

## Setup

- Put the phone on a fixed tripod or another mount that does not move during the delivery.
- Record in landscape.
- Use 1080p and 60 fps when the phone offers them. After recording, read the file. The container may not actually say 60 fps.
- Place the camera side-on to the bowler's run-up and delivery stride.
- Keep the whole delivery stride in the frame.
- Keep the whole bowler in the frame, including the shoes and the bowling arm.
- Use lighting in which the bowler is clearly visible.
- Do not pan or follow the bowler with the camera.
- Do not use digital zoom.
- Avoid other players overlapping the bowler.
- Frame the bowler large enough that the body is easy to see, without cutting off the shoes or the bowling hand.
- Keep the original file. Do not crop, filter, stabilize, or re-encode it before inspection.
- Record several deliveries without changing the camera setup.

## Identifiers and privacy

Use anonymous ids only. Bowlers are `B01`, `B02`, and so on. Deliveries are `D01`, `D02`, and so on. Do not put a person's name in a filename, a CSV, or a note.

Before recording, tell the participant what the video will be used for, that it stays on the project machine, and that it is not a medical assessment. Record only after they agree. They can ask for the file to be deleted. Do not commit videos or personal data to git.

## Metadata to write down

For each delivery, record only what is known:

- `bowler_id` and `delivery_id`
- recording date
- video filename
- phone model, if known
- width, height, and encoded FPS from the inspection tool, not from memory
- that the intended view was side-on
- notes about anything that changed, such as a person walking through the frame

`camera_distance_m` stays empty unless someone actually measured it.

## What 2D video cannot support

This is one camera. It does not provide laboratory 3D joint angles, ground reaction forces, or injury risk. MediaPipe can follow the wrong person, and a foot point can sit off the shoe. Encoded FPS is not a measured capture clock. A clear picture is not a validated recording.

## Before any measurement

From the `backend` directory, inspect the new file and read every warning. A report with no error only means the file opened and its header could be read. It does not accept the video for analysis.

Engineering clips already in `raw_videos/stress_tests/` are not a substitute for these original recordings.
