# First-video pilot checklist

Use this after an original side-on recording. Reports go under `backend\debug_output\`, which is not committed. A completed command is not scientific validation.

Record the original file and do not crop, filter, or re-encode it. Follow `RECORDING_PROTOCOL.md`. There is no command that sets a required camera distance.

From the `backend` directory:

1. Inspect the file. Read every warning. `error: unavailable` means the file could be described, not that it is suitable.

```powershell
.\.venv\Scripts\python.exe -m app.video.inspect path\to\delivery.mp4
```

2. Run the pose review and look at the exported frames. Check the shoe, ankle, knee, hip, and bowling arm by eye. Dots on the grass or on another person are raw model output. The tool does not move them.

```powershell
.\.venv\Scripts\python.exe -m app.quality.pilot_review --video path\to\delivery.mp4 --output debug_output\pilot_review --frame 0
```

Repeat `--frame` for each zero-based index you want to see. The model file `models\pose_landmarker_full.task` is required.

3. Mark BFC, FFC, and Release in the annotation window. Pass a labels file under `debug_output` so the dataset template is not edited by accident. Save with S, then Y. Saving writes a filename sidecar next to the labels file. That sidecar is the file name only, not a hash.

```powershell
.\.venv\Scripts\python.exe -m app.annotations.annotate --video path\to\delivery.mp4 --bowler B01 --delivery D01 --labeler SS --labels debug_output\pilot_sessions\phase_labels.csv --markers debug_output\pilot_sessions\marker_positions.csv
```

4. Create the session manifest from the same unedited video and the same ids. `--front-leg` is the anatomical side, `left` or `right`, not the side of the picture. There is no later command to add the front leg. If you omit it, create a new manifest file with `--front-leg`. The existing file will not be overwritten.

```powershell
.\.venv\Scripts\python.exe -m app.pilot.session_manifest create --video path\to\delivery.mp4 --bowler B01 --delivery D01 --front-leg right --output debug_output\pilot_sessions\B01_D01.json
```

5. Verify the manifest against that same file.

```powershell
.\.venv\Scripts\python.exe -m app.pilot.session_manifest verify --manifest debug_output\pilot_sessions\B01_D01.json --video path\to\delivery.mp4
```

A match means the bytes are the same. It does not confirm the camera view or the bowler.

6. There is no command to set `camera_side_on_confirmed` or `full_body_visibility_confirmed`. They stay false. The measurement report will say those checks are unconfirmed. That is not approval, and it is not a reason to edit the JSON by hand.

7. Run the knee-angle command only after you have looked at the sidecar filename and decided it belongs to this video. `--confirm-label-link` records that decision. It does not turn the filename into a hash, and it does not prove the labels were drawn on these bytes.

```powershell
.\.venv\Scripts\python.exe -m app.pilot.manual_measurement --video path\to\delivery.mp4 --manifest debug_output\pilot_sessions\B01_D01.json --labels debug_output\pilot_sessions\phase_labels.csv --output debug_output\pilot_sessions\B01_D01_measurement.json --confirm-label-link
```

8. Open the JSON. An unavailable angle is null, not zero. Read `review_status`, `warnings`, and `limitations`. Keep the manifest, the measurement JSON, and the pose-review folder for a later manual reference comparison. This checklist does not create reference angles or an accuracy statistic.
