# Fast Bowling V1 — frontend

React and TypeScript interface for the local FastAPI prototype. This step uploads one delivery video and shows the inspected session. It does not run pose review or knee measurement.

## Requirements

- Node.js 20 or newer (developed on Node.js 24)
- The backend API on `http://127.0.0.1:8000`

## Install and run

From this `frontend` directory:

```powershell
npm install
npm run dev
```

Vite serves `http://127.0.0.1:5173`. Refreshing `/sessions/{session_id}` works in the Vite dev server.

Start the API from `backend` with one worker:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --workers 1
```

## Environment

`VITE_API_BASE_URL` defaults to `http://127.0.0.1:8000`. Copy `.env.example` to `.env` only if the API is on another local URL. CORS on the API allows `http://localhost:5173` and `http://127.0.0.1:5173`.

## What this app does

- Checks `GET /health`
- Uploads `POST /api/sessions` with fields `video`, `bowler_id`, `delivery_id`, and optional `front_leg`
- Loads `GET /api/sessions/{session_id}`
- Starts and polls `POST` and `GET /api/sessions/{session_id}/pose-review`
- Shows the completed diagnostic report and only the overlay PNGs the server exported
- Shows any decoded original frame from `GET /api/sessions/{session_id}/video/frames/{index}`

Frame indexes are zero-based. Previous, next, jump, and the slider stay inside `0 .. decoded_frame_count - 1`. Arrow keys move one frame when the original-frame section is focused, and they do not fire while typing in the jump field. The image is shown only after the response for that exact index arrives. The original image has no pose overlay.

## Manual events

Open a session, then choose **03 Event Annotation**. Wait until the original frame image is visible. The displayed index is the only index you can mark. **Clear BFC**, **Clear FFC**, or **Clear Release** removes that one unsaved mark. **Clear unsaved selection** removes all three.

- **Mark BFC** stores the displayed frame as back-foot contact. BFC is optional.
- **Mark FFC** stores the displayed frame as front-foot contact. FFC is required.
- **Mark Release** stores the displayed frame as ball release. Release is required.

FFC must be an earlier index than Release. If you also mark BFC, it must be earlier than FFC. The page does not reorder the frames you chose. Nothing is inferred from pose or foot motion.

Choose the bowler's anatomical front leg, left or right. Tick **I confirm this front leg** separately from **I confirm these labels belong to this video**. The second tick is a human check that the marks belong to this clip. It is not a hash of the label file. Side-on view and full-body visibility are not set here.

**Save labels** sends `PUT /api/sessions/{session_id}/labels` with `replace_existing` false. The page says the labels are saved only after the server accepts them. If labels were already saved, they are shown and cannot be replaced from this screen. Correcting an existing label file is deferred.

## Knee kinematics

Open **04 Knee Kinematics** after labels are saved. The page lists the saved FFC frame, Release frame, front leg, and whether those confirmations were recorded. If any of those is missing, **Start measurement** stays off and the page links back to Event Annotation.

Tick **I confirm again that these saved labels belong to this video** before starting. That tick is sent as `confirm_label_link`. It is not turned on for you.

The page polls `GET /api/sessions/{id}/measure` about every 2 seconds while the job is queued or running, then loads `GET /api/sessions/{id}/report`. A completed report is shown and is not replaced by another job. Each angle comes from `angle_degrees`. A null or unavailable angle is shown as Unavailable, not 0. Visibility on a landmark is not accuracy.

**Download CSV** saves one FFC row and one Release row from that stored report. `angle_degrees` is in degrees. A blank angle is unavailable, not 0. The file name uses the anonymous session id. **Download JSON** still saves the stored report for technical inspection. There is no PDF. Pose review is not started by this page. The same two downloads are on **05 Analysis Report** when a measurement is stored.

Accepted filename extensions shown in the form: `.mp4`, `.mov`, `.avi`. The stated size limit is 80 MiB. The server still accepts or rejects the file.

A created session means the video was stored and inspected. It does not mean biomechanical analysis is complete. Encoded FPS is the container rate. Side-on view and full-body visibility stay unconfirmed until a person sets them. A file hash is not scientific suitability.

## Checks

```powershell
npm run typecheck
npm test
npm run build
```

No ESLint config is included in this step.
