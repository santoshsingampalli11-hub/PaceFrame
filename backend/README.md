# Fast Bowling V1 — backend

Python backend for the Fast Bowling V1 prototype. It currently has:

- a FastAPI app that serves identification and health checks,
- a video module that opens local video files with OpenCV and reads their metadata and frames, and
- a pose module that runs MediaPipe Pose on those frames and returns body landmarks, and
- a quality module that summarises pose coverage and tracking diagnostics from those landmarks, and
- an annotation module for manual BFC / FFC / release reference labels.

**Quality diagnostics do not accept or reject videos.** Manual phase labels are annotator-selected frame indices, not laboratory ground truth. Automatic BFC / FFC / release detection is not implemented. There are no cricket-specific biomechanical metrics.

Requires Python 3.12.

## Setup

From this `backend` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

`requirements.txt` pins every package, including indirect dependencies, to the versions the tests were run with. This keeps installs reproducible.

If activation is blocked by execution policy, call the virtual environment interpreter directly, for example `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

If an older environment already has `opencv-python` installed, uninstall it first (`python -m pip uninstall opencv-python`). MediaPipe depends on `opencv-contrib-python`, and having both installed puts two conflicting copies of `cv2` in the environment.

### Download the pose model

MediaPipe needs a model file, which is not stored in git (`*.task` is ignored). From this `backend` directory:

```powershell
New-Item -ItemType Directory -Force models
Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task" -OutFile models\pose_landmarker_full.task
```

This is version 1 of the "full" Pose Landmarker model (9,398,198 bytes, SHA-256 `5134A3AAD27A58B93DA0088D431F366DA362B44E3CCFBE3462B3827A839011B1`). A fixed version is used instead of `latest` so results stay reproducible. Check the file with `Get-FileHash models\pose_landmarker_full.task`.

## Run the server

From this `backend` directory, with the virtual environment active:

```powershell
uvicorn app.main:app --reload
```

The API listens on `http://127.0.0.1:8000`.

- `GET /` identifies the API.
- `GET /health` reports that the process is running.

Interactive docs are available at `http://127.0.0.1:8000/docs`.

## Run tests

From this `backend` directory, with the virtual environment active:

```powershell
pytest
```

The video tests generate small synthetic videos (solid grey frames, not cricket) in a temporary directory, so no real video files are needed or committed.

Pose tests that run the real model are skipped if the model file has not been downloaded. One optional test runs a real video through the whole video → pose pipeline:

```powershell
$env:POSE_TEST_VIDEO = "C:\path\to\video.mp4"
pytest tests/test_pose.py -k real_video
```

It is a **REAL-WORLD STRESS TEST**: not scientific validation, not training data, and not ground truth. It only checks that the pipeline runs and finds a pose somewhere. Detection rate is not model accuracy. The normal suite still passes when `POSE_TEST_VIDEO` is unset.

## Security notes (local prototype)

- The API does not accept file uploads or paths.
- Unhandled API errors return `{"detail":"Internal server error"}` and do not include stack traces or filesystem paths.
- Video and pose errors use the file name, not the full path.
- The debug tool refuses to overwrite its input video.
- No API keys or secrets are stored in the repository.
- Personal videos, model files (`*.task`), `debug_output/`, and `fast_bowling_dataset/raw_videos/` are gitignored.

Do not commit personal bowling videos.

## Video module (`app/video/`)

The video module reads a video file and hands its frames to later processing steps. It does not depend on FastAPI, so it can be used and tested on its own.

### Usage

```python
from app.video import iter_frames, read_video_metadata

metadata = read_video_metadata("delivery.mp4")
print(metadata.width, metadata.height, metadata.fps)
print(metadata.frame_count, metadata.duration_seconds)

for frame in iter_frames("delivery.mp4"):
    print(frame.index, frame.timestamp_seconds, frame.image.shape)
```

### Metadata

`read_video_metadata(path)` returns a `VideoMetadata` with:

| Field | Meaning |
| --- | --- |
| `width`, `height` | Frame size in pixels |
| `fps` | Frames per second, as reported by the file (encoded/container FPS, not a measured capture rate) |
| `frame_count` | Number of frames, as reported by the file |
| `duration_seconds` | `frame_count / fps` |

It also decodes the first frame, so a file whose header is readable but whose video data is not is rejected here.

### Frames

`iter_frames(path)` yields one `VideoFrame` at a time, in order:

- `index`: 0 for the first frame, then 1, 2, and so on.
- `timestamp_seconds`: `index / fps`.
- `image`: the decoded frame as a NumPy array in OpenCV's BGR colour order, shape `(height, width, 3)`, type `uint8`.

Frames are not resized, filtered, smoothed, or colour-converted. Frames are read one at a time, so a whole video is never held in memory unless the caller collects it.

### Errors

| Situation | Error |
| --- | --- |
| Path does not exist or is not a file | `FileNotFoundError` |
| OpenCV cannot open the file (corrupt, empty, not a video, unsupported codec) | `VideoReadError` |
| File reports a missing, zero, negative, or non-numeric FPS, frame size, or frame count | `VideoReadError` |
| No frame can be decoded | `VideoReadError` |

No placeholder values are returned: if a video cannot be described reliably, the call fails with a message naming the file and the problem. For `iter_frames`, errors are raised when iteration starts, not when the function is called.

### Known limitations

- **Codec support depends on the OpenCV build.** Videos are opened with the FFmpeg backend bundled in `opencv-contrib-python`. The tests confirm AVI (MJPG), MP4 (MPEG-4 Part 2), and MOV (MPEG-4 Part 2) files. Real smartphone videos usually use H.264 or HEVC; H.264 normally works, but HEVC and other codecs are not guaranteed on every machine. Unsupported files are rejected with `VideoReadError`.
- **Timestamps assume a constant frame rate.** Many smartphones record variable frame rate video. In that case `index / fps` is only an approximation of when each frame was captured.
- **Encoded FPS is not capture FPS.** `CAP_PROP_FPS` is the rate stored in the container. It is not independently measured from the camera shutter, and it can be a non-integer value such as 29.97.
- **`frame_count` comes from the file header.** Some containers only estimate it, so it can differ from the number of frames `iter_frames` actually yields. Duration uses the header count. If the decoded count differs, a warning is logged; timestamps still use `index / fps`.
- **Orientation.** OpenCV may rotate frames according to the phone's rotation metadata. Check orientation on real recordings before relying on it.
- **Truncated videos.** If decoding stops partway through a file, iteration ends at the last good frame; this looks the same as reaching the end of the video.
- **No quality checks.** Resolution, frame rate, camera angle, lighting, and similar suitability checks are not implemented.

## Pose module (`app/pose/`)

### What it does

Pose estimation means finding body landmarks, such as shoulders, knees, and ankles, in an image. The pose module takes each decoded `VideoFrame` from the video module and returns a `PoseFrame` saying whether a person was found and, if so, where each landmark is in the image:

```text
video file → iter_frames() → PoseEstimator → PoseFrame (landmarks per frame)
```

It is the step before bowling phase detection and biomechanics, and it does neither. It does not depend on FastAPI.

### MediaPipe's role and how to replace it

[MediaPipe Pose Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker) is Google's pretrained pose model. Here it is used through version 1.0.1 of the `mediapipe` package, the current official release, which supports Python 3.12. Recent releases, including 0.10.35 and 1.0.1, no longer include the old `mediapipe.solutions.pose` API, so the Tasks API (`PoseLandmarker`) is used.

MediaPipe appears in exactly one file, `app/pose/mediapipe_estimator.py`. Everything else, and every later module, should use only the estimator-independent types exported by `app.pose`:

| File | Contents | Uses MediaPipe? |
| --- | --- | --- |
| `landmarks.py` | `Landmark`, `PoseFrame`, `LANDMARK_NAMES`, `SKELETON_CONNECTIONS` | No |
| `estimator.py` | `PoseEstimator` interface, `estimate_video_poses`, `PoseEstimationError`, frame checks | No |
| `mediapipe_estimator.py` | `MediaPipePoseEstimator`, and conversion from MediaPipe results to `PoseFrame` | Yes |
| `debug.py` | DEBUG overlay drawing and the debug video tool | Only for the command-line tool |

A `PoseEstimator` is anything with an `estimate(frame: VideoFrame) -> PoseFrame` method. To try another model such as RTMPose, write a new estimator that maps its keypoints onto the same landmark names. Code that consumes `PoseFrame` does not change.

### Usage

```python
from app.pose import estimate_video_poses
from app.pose.mediapipe_estimator import MediaPipePoseEstimator

with MediaPipePoseEstimator() as estimator:
    for pose in estimate_video_poses("delivery.mp4", estimator):
        if pose.pose_detected:
            knee = pose.landmarks["left_knee"]
            print(pose.frame_index, pose.timestamp_seconds, knee.x, knee.y, knee.visibility)
            print(pose.pixel_xy("left_knee"))
```

MediaPipe runs in video mode, which tracks the person from one frame to the next. Frames must therefore be given in order, and each video needs its own `MediaPipePoseEstimator`. Out-of-order frames raise `PoseEstimationError`.

### Landmark representation

`PoseFrame`:

| Field | Meaning |
| --- | --- |
| `frame_index`, `timestamp_seconds` | Copied unchanged from the `VideoFrame` |
| `image_width`, `image_height` | Size in pixels of the image the pose was estimated on |
| `landmarks` | `dict` from landmark name to `Landmark`; empty when no pose was detected |
| `pose_detected` | `True` when `landmarks` is not empty |
| `pixel_xy(name)` | Landmark position in pixels |

`Landmark` has `name`, `x`, `y`, `visibility`, and `presence`. There are 33 landmark names, listed in `LANDMARK_NAMES`, such as `"left_knee"` and `"right_ankle"`. **Left and right are the athlete's own sides, not the viewer's.**

### What the numbers mean

- **`x`, `y` are normalized image coordinates, not distances.** `x` is the fraction of the image width from the left edge and `y` the fraction of the image height from the top edge, so y grows downward. For example, `x = 0.5, y = 0.25` means the middle of the image horizontally, a quarter of the way down. Values can be slightly below 0 or above 1 when the model places a landmark outside the frame.
- **Use pixels for geometry.** In a 1920×1080 video, 0.1 of the width (192 px) and 0.1 of the height (108 px) are different distances, so angles computed from normalized coordinates would be distorted. `pixel_xy()` converts using the frame size. Pixels are still image measurements, not centimetres.
- **`visibility` and `presence` are model scores in 0 to 1.** `visibility` is the model's estimate that the landmark is visible rather than hidden, and `presence` that it is inside the image. They are preserved as MediaPipe reports them. They are not measurement accuracy, and no cut-off such as "above 0.8 is reliable" has been validated. Choosing any such threshold is future validation work.
- **Deliberately not kept:** MediaPipe's `z` (a relative depth estimated from a single image) and its "world landmarks" (metric 3D coordinates estimated by the model). This project is a 2D system, and neither is a measurement.

### Why pose output is not accurate biomechanics

MediaPipe estimates where joints appear in a 2D image from a single camera. It does not measure the body.

- **Estimates, not measurements.** Landmarks are a neural network's best guess and can be off by several pixels, or badly wrong on blurry or unusual frames.
- **No depth.** Movement toward or away from the camera is invisible, and anything not perpendicular to the camera appears foreshortened.
- **Self-occlusion.** In a side-on view the far-side limbs are hidden behind the body, and the model guesses their position.
- **Left/right confusion.** In side views the model can swap left and right limbs.
- **Fast motion.** Motion blur at typical smartphone shutter speeds degrades landmarks, especially wrists and hands.
- **Training data.** The model was not trained specifically on cricket bowling actions.
- **One person.** The estimator is configured for one pose (`num_poses=1`). If several people are in view, MediaPipe chooses which one to track.

Any measurement built on these landmarks therefore needs its own validation before it can be trusted. This module makes no claim about 3D joint positions, forces, joint loading, injury, or medical conditions.

### Debug visualization

To check by eye whether MediaPipe is tracking the athlete, from this `backend` directory:

```powershell
python -m app.pose.debug "C:\path\to\video.mp4"
```

This writes `debug_output/<video name>_pose_debug.mp4` and prints how many frames had a detected pose. `debug_output/` is ignored by git. Use `--output` to choose another path and `--model` to try another model file. The tool refuses to overwrite the **input** video. Running it again with the same output path replaces the previous debug file on purpose.

Each output frame is the original frame with the following drawn on a copy:

- a red `DEBUG pose overlay` label with frame number and timestamp, plus `NO POSE DETECTED` when nothing was found;
- the skeleton, with the athlete's **left side in orange**, **right side in cyan**, and connections across the body in white. This makes left/right swaps easy to see;
- a dot on every landmark, shaded continuously from red (visibility 0) to green (visibility 1). No landmark is hidden because of a low score. MediaPipe's own drawing helper hides landmarks below a fixed 0.5 cut-off, so it is not used.

This is a debugging aid. It does not measure anything.

### Pose-estimation errors

| Situation | Error |
| --- | --- |
| Model file missing | `PoseEstimationError` with the download URL |
| Model file cannot be loaded by MediaPipe | `PoseEstimationError` |
| Frame image not a NumPy array, not `(height, width, 3)`, empty, or not `uint8` | `ValueError` |
| Frame timestamp not after the previous one | `PoseEstimationError` |
| MediaPipe fails while processing a frame | `PoseEstimationError`, naming the frame index |
| No person in the frame | Not an error: `PoseFrame` with `pose_detected == False` |

### Real-world stress test (not validation)

The pipeline was run on one real phone clip of a bowling run-up. It was not standardized or side-on, the camera moved, and there was no ball release. The clip is 848×478 H.264 at a reported 30.03 FPS, with 226 frames. It is kept outside the repository. This only checks that pose estimation behaves sensibly on real footage and must not be used to validate any measurement.

- The clip has a constant frame rate: frames are 33.30–33.41 ms apart, and `index / fps` matches the container's own frame timestamps within 0.06 ms. It has no rotation metadata.
- A pose was found in 178 of 226 frames (78.8%). The misses were the first 38 frames and the last 10; there were no gaps once tracking started.
- Many of those detections depend on video-mode tracking. On several mid-run-up frames, MediaPipe in single-image mode, with no tracking from earlier frames, found no person at all.
- Landmarks are sensitive to framing. Running the same frame as-is and padded to a square moved body joints by a median of about 3 px, and occasionally 13–33 px, on an athlete roughly 120 px tall. This shows that no systematic distortion comes from non-square frames, despite MediaPipe's `NORM_RECT without IMAGE_DIMENSIONS` log warning. It also shows how imprecise landmarks are when the athlete is small in the frame.
- The first 38 misses are frames where the athlete stands still and is small in a wide frame. Cropping the first frame around the athlete made MediaPipe detect them, so subject size relative to the frame matters. How large the bowler must appear is a question for the future recording standard and quality checks. No limit has been set.
- During the side-on part of the run-up, the skeleton visibly follows the athlete's legs, arms, and trunk. Between consecutive frames, the midpoint between the hips moved a median of about 4 px, and never more than 18 px, so there were no sudden jumps to another person.
- The far-side (left) arm was mostly hidden. MediaPipe gave the left wrist a median visibility of 0.24, compared with 0.78 for the right. This is the expected self-occlusion effect.
- When a second person stood close behind the athlete, tracking stayed on the athlete.
- Tracking degraded when the athlete ran away from the camera and when the camera panned toward them near the end. Heavy motion blur and a subject partly leaving the frame produced less plausible limb positions.

## 2D geometry (`app/biomechanics/`)

`geometry.py` contains only plane geometry: `Point2D`, Euclidean `distance`, and the unsigned interior angle `angle_abc_degrees` (vertex at B, result in degrees, range 0..180). It does not import MediaPipe, OpenCV, or FastAPI, and it does not define bowling metrics, phases, or thresholds.

## Quality diagnostics (`app/quality/`)

`diagnose_pose_frames(frames)` summarises a sequence of generic `PoseFrame` results. It does not import MediaPipe or FastAPI.

| Output | Meaning |
| --- | --- |
| `pose_coverage` | Detected-pose frames divided by sequence length. Detection is not measurement accuracy. |
| `longest_run_without_pose`, `missing_pose_run_count` | Gaps in detection in the given sequence |
| `landmark_signals` | Per-landmark counts and mean model visibility/presence where those scores exist. Visibility is not accuracy. |
| `hip_centre_motion` | Normalized 2D image-coordinate displacement of the midpoint of `left_hip` and `right_hip` between consecutive sequence frames. Uses landmark `x`,`y` directly (`hypot(dx, dy)`); not pixels, metres, centre of mass, stride, or velocity. Missing poses and missing hips are not bridged. |

There is no pass/fail field and no acceptance threshold.

`landmark_steps` and `landmark_deviations` in `app.quality.temporal` describe normalized image movement of shoulders, hips, knees, ankles, heels, foot-index points, and wrists. A step is `hypot(dx, dy)` between frame indices that differ by 1, and only when both frames contain that landmark. A deviation is the distance from the middle point to the midpoint of its two neighbors. Fast real motion can be a large step with a small deviation. These numbers do not name the bowler and do not correct landmarks. `exploratory_large_steps(..., None)` flags nothing.

`app.quality.scene_change.visual_changes` scores consecutive images by the mean absolute grayscale difference divided by 255. A high score is a possible visual discontinuity. Camera motion and lighting can raise it. Nothing is flagged unless the caller passes an exploratory limit. The score does not edit pose landmarks.

## Contact candidates (`app/phases/`)

`search_contact_candidates` looks for frames where an anatomical foot is briefly still in the image. It does not detect ball release, measure a force, or confirm that a shoe touched the ground.

BFC is back-foot contact. FFC is front-foot contact. The caller must say which athlete side, `left` or `right`, is the back foot and which is the front foot. Those words are the athlete's sides, not the sides of the picture. If that mapping is omitted, the function abstains.

`ContactHeuristicConfig.stable_displacement` is a provisional maximum normalized step. The default `None` abstains. A returned pair exists only when there is one BFC candidate, one later FFC candidate, and no listed visual break between them. Otherwise the candidates stay separate or the search abstains. `provisional_score` is always `None`.

`compare_reference_frame` subtracts a manual reference frame from a candidate frame. A missing candidate is an abstention, not a zero error. A missing reference makes the comparison unavailable. Dividing by encoded FPS is an approximate time error, not a capture-clock measurement. Manual labels are not laboratory ground truth.

```powershell
.\.venv\Scripts\python.exe -c "from app.phases import ContactHeuristicConfig, search_contact_candidates; print(search_contact_candidates([]))"
```

From this `backend` directory. Do not treat a candidate from a broadcast clip as a verified contact.

```python
from app.pose import estimate_video_poses
from app.pose.mediapipe_estimator import MediaPipePoseEstimator
from app.quality import diagnose_pose_frames

with MediaPipePoseEstimator() as estimator:
    poses = list(estimate_video_poses("delivery.mp4", estimator))

print(diagnose_pose_frames(poses))
```

## Manual phase labels (`app/annotations/`)

`PhaseLabel` stores one delivery's manual reference frames:

- **BFC** — back-foot contact
- **FFC** — front-foot contact
- **Release** — ball release

Frame indices are **0-based**, matching the video reader. Any subset may be empty. Present frames must be integers `>= 0` and strictly ordered (BFC < FFC < Release). These labels are not biomechanical measurements and will later be used to evaluate automatic Phase 4 detection. Automatic detection is not implemented.

CSV read/write uses the existing `fast_bowling_dataset/phase_labels/phase_labels.csv` header. Duplicate `(bowler_id, delivery_id)` rows are rejected. Updates replace that key in place and keep file order. `validate_phase_labels(label, total_frame_count)` checks bounds without opening a video.

Do not add fabricated deliveries to the template CSV.

## Local annotation window

This opens **your** video and shows its decoded frames. It does not create a bowler animation, and it does not decide BFC, FFC, or release.

From the `backend` directory:

```powershell
python -m app.annotations.annotate --video path\to\delivery.mp4 --bowler B01 --delivery D01 --labeler SS
```

`--bowler` and `--delivery` are required anonymous ids. `--labels` and `--markers` choose the two output files independently. Their defaults are the dataset template and `marker_positions.csv` beside it. Engineering runs must pass both flags and write under `debug_output/`, which is gitignored. Do not point a smoke test at `fast_bowling_dataset/phase_labels/phase_labels.csv`.

The two files are saved one after the other. That is not one atomic transaction. If the phase-label file is written and the marker file then fails, the window reports that failure and the delivery stays unsaved. A click is restored only when its frame matches the saved event frame. A side file next to the phase-label CSV records the video **file name** for each delivery. Opening a different video with the same bowler and delivery ids does not load those labels until you press L.

| Key | Action |
| --- | --- |
| Right arrow or D | Next decoded frame |
| Left arrow or A | Previous decoded frame |
| G, digits, Enter | Jump to a zero-based frame (decoded from the start, not a container seek) |
| 1, 2, 3 | Select BFC, FFC, or Release |
| Left click | Store the selected event on the **current** frame at that point on the bowler |
| C | Clear the selected event and its click |
| T | Toggle optional MediaPipe dots (hips, knees, ankles, feet, shoulders, elbows, wrists) |
| Space | Play or pause |
| S, then Y | Save. Nothing is written until Y |
| Q or Esc | Quit. If there are unsaved edits, Y discards them |

Three different things can appear on a frame:

1. **Event frame** — the zero-based index you chose for BFC (back-foot contact), FFC (front-foot contact), or release. Stored in `phase_labels.csv`.
2. **Manual marker** — where you clicked on that same frame. Stored only in the marker sidecar. It is not a measured joint or ball coordinate.
3. **Pose overlay** — optional MediaPipe dots on the real frame. Turn them off with T. They are not BFC, FFC, or release, and marking still works if pose fails.

The picture keeps the video's aspect ratio. Clicks are read in the shown frame, not scaled a second time by the window size, so a resized or high-DPI window does not move the saved point. Clicks in the black margin are ignored. Press **P** to cycle the pose-dot color. The default is a black center with a white ring. Color does not move a landmark or make it more accurate. Press **R** and drag a box if you want those dots limited to the bowler. That box is not tracking: if the bowler leaves it, press **R** and draw it again, or press **U** to use the full frame. Press **F** to correct one foot landmark, then **[** or **]** to choose the athlete's left or right ankle, heel, or foot index. Click only if that point is visible. **X** removes the correction and leaves the raw prediction. **K** switches among raw dots, corrections, and both. Corrections are stored in a separate file and are not mixed into the pose result or the event markers. Dots can still sit on the grass. They never move the gold, green, or magenta clicks. Timestamps use `index / encoded fps`. The header frame count can disagree with the number of decoded frames; the tool shows both once decoding reaches the end.

For a first standardized clip, use ids `B01` and `D01`, step to the frame where the back foot actually meets the ground, press 1, and click that contact point. Repeat for the front foot and for the frame where the ball leaves the hand. If a moment is not clear, leave it unset. Then press S and Y.

The source video is not modified.

## Dataset templates

The repository root has `fast_bowling_dataset/` with header-only CSV schemas for metadata, manual phase labels, landmarks, measurements, and validation. See that folder's README. No videos or measurements are stored there yet.

## Security and logging

The API logs unhandled exceptions at ERROR level and returns a generic 500 body. Video-reader warnings (for example a header frame-count that does not match the number of decoded frames) go to the `fast_bowling.video` logger. They are not measurements.

Known benign pytest warning: Starlette reports that `TestClient` prefers a package named `httpx2`, which is not on PyPI. Tests still use `httpx`.

## Intentionally not implemented

- Pose/video accept/reject thresholds (diagnostics exist; gates do not)
- Phase 4: automatic BFC / FFC / release detection
- Cricket-specific biomechanical measurements (knee angle interpretation, stride, release height, scoring)
- Video upload API
- Region-of-interest cropping or athlete selection
- Measurement validation
- Database, authentication, reports, and deployment
- Frontend
- 3D biomechanics, forces, injury prediction, or medical claims

