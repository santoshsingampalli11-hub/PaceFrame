# Fast-bowling V1

B.Tech capstone prototype: analyze **standardized side-on smartphone video** of cricket fast bowling and extract a small set of scientifically defensible **2D** kinematic measurements.

This is a single-camera smartphone system, not laboratory motion capture. It does not claim 3D biomechanics, ground reaction forces, joint loading, internal tissue forces, injury prediction, or medical diagnosis.

## Current status

| Phase | Status |
| --- | --- |
| 1. Backend foundation (FastAPI) | Hardened |
| 2. Video reading (OpenCV) | Hardened |
| 3. Pose estimation (MediaPipe Tasks) | Hardened |
| 2D geometry helpers (`distance`, unsigned vertex angle) | Complete |
| Dataset templates | Prepared |
| 3.5 Pose quality diagnostics (no accept/reject) | Complete |
| Manual phase-label infrastructure | Complete |
| Local real-video annotation window | Complete |
| 4. Automatic bowling phase detection | Not part of the delivered application |
| Biomechanical metrics | 2D front-knee angle at manually marked FFC and Release; not a 3D joint angle and not a completed accuracy study |

Project rules are in `.cursor/rules/`. Backend details are in `backend/README.md`. Dataset rules are in `fast_bowling_dataset/README.md`.

## Architecture

```text
Video file
  → video reader (OpenCV)
  → PoseEstimator abstraction
  → PoseFrame / generic landmarks
  → 2D geometry (distance, unsigned angle)
  → quality diagnostics (coverage, missing-pose runs, visibility, hip-centre motion)
  → manual phase labels (BFC / FFC / release reference frames, marked on the real video)
  → (automatic phase detection is not implemented)
```

MediaPipe is isolated in `backend/app/pose/mediapipe_estimator.py`. Later biomechanics code must use only the generic landmark types.

## Setup and tests

See `backend/README.md` for virtual environment, dependencies, the pose model, FastAPI, and pytest. See `frontend/README.md` for the web application. See `docs/DEPLOYMENT.md` for the local run. The app stays on one computer. It is not a public deployment.

## Submission notes

- `docs/PROBLEM_STATEMENT.md`
- `docs/NOT_BUILT_AND_WHY.md`
- `docs/COACH_CONSULTATION.md`

A person marks front-foot contact and release. The application does not detect those events automatically, does not give coaching recommendations, and does not claim laboratory or clinical accuracy.

Do not use the earlier moving-camera run-up clip, or broadcast stress-test footage, as validation, training data, or ground truth.
