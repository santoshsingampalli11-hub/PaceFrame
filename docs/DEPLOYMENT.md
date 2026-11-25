# PaceFrame V1 deployment

PaceFrame has no user accounts and no authentication. A session id is not authorization. Do not put this service on the public internet. Unrestricted public deployment is blocked.

Run one application process. The upload limit, job limit, and in-memory rate limiter are not shared across workers or replicas.

The pose model is the existing MediaPipe Pose Landmarker task file at `backend/models/pose_landmarker_full.task`. It is not in git. Use the file you already hash-checked. Do not bake demonstration videos or session reports into an image.

Container build and run were not executed on the development machine because Docker is not installed.

## Local development

From `backend`, with the production virtual environment:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

From `frontend`:

```powershell
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` and `/health` to `127.0.0.1:8000`. The browser bundle does not call loopback unless `VITE_API_BASE_URL` is set.

Stop each process with Ctrl+C in its own window. Do not stop unrelated processes.

## Production build without Docker

```powershell
cd frontend
$env:VITE_API_BASE_URL = ""
npm run build
```

Serve `frontend/dist` on the same origin as the API. Proxy `/api/` and `/health` to the one Uvicorn process. Keep the proxy body limit at about 85 MiB and the read timeout at about 300 seconds.

## Environment

See `.env.example`. Do not commit real values.

| Variable | Role |
|---|---|
| `FAST_BOWLING_SESSION_ROOT` | Persistent session directory. Unset uses `backend/local_sessions`. A relative value is resolved from the backend directory. |
| `FAST_BOWLING_MAX_UPLOAD_BYTES` | Default 80 MiB. |
| `FAST_BOWLING_MAX_DECODED_FRAMES` | Default 1800. The demonstration clip is 223 frames. |
| `FAST_BOWLING_MAX_DURATION_SECONDS` | Default 30. One delivery, including a 60 fps approach. |
| `FAST_BOWLING_MAX_POSE_JOBS` | Default 1. Pose review and measurement each have their own cap of this size. |
| `FAST_BOWLING_CORS_ORIGINS` | Comma-separated origins. `*` is rejected. Credentials are off. |
| `FAST_BOWLING_TRUSTED_HOSTS` | Hostnames only. `X-Forwarded-*` is not trusted. |
| `FAST_BOWLING_RATE_LIMIT` | `1` or `0`. Default on. Counts uploads and new jobs in this process. |
| `FAST_BOWLING_UPLOAD_LIMIT` | Default 40 uploads per window. |
| `FAST_BOWLING_JOB_LIMIT` | Default 20 pose-review or measurement starts per window. |
| `FAST_BOWLING_RATE_WINDOW_SECONDS` | Default 600. |
| `VITE_API_BASE_URL` | Empty for same-origin `/api`. Set an `https://` origin only when the API is on another host. |

Startup fails with a clear error if the session directory cannot be created or written. Existing files are not deleted. There is no database migration.

## Docker

Files:

- `deploy/Dockerfile.backend`
- `deploy/Dockerfile.frontend`
- `deploy/nginx.conf`
- `deploy/docker-compose.yml`

From the repository root, when Docker is available:

```powershell
docker compose -f deploy/docker-compose.yml up --build
```

The published ports are bound to `127.0.0.1` only. The volume `paceframe-data` is empty until someone uploads. Do not mount `backend/local_sessions` into it.

Open `http://127.0.0.1:8080`. Health: `http://127.0.0.1:8080/health`.

Stop:

```powershell
docker compose -f deploy/docker-compose.yml down
```

`down` without `-v` keeps the volume. `down -v` deletes that deployment's uploads. It does not delete `backend/local_sessions`.

## What a private deployment must not do

- Do not mount the existing demonstration sessions.
- Do not publish port 8000 or 8080 on a public address.
- Do not treat the session id as a password.
- Do not run more than one Uvicorn worker.

## Backup and rollback

Keep a separate copy of the project before replacing a running copy. Do not commit that copy, demonstration videos, or `backend/local_sessions`.

To leave a bad deployment, stop its process or run `docker compose ... down`, and do not copy its storage over `backend/local_sessions`. For a local demonstration, use the Vite server and one Uvicorn process. A container image was not built or run for this submission.

## Known limits

- No authentication.
- Rate limits reset when the process restarts and are not shared by a second process.
- A failed pose-review rerun keeps the previous successful report and overlays. A successful rerun replaces them.
- Labels cannot be replaced after `measurement/report.json` exists.
- Knee angles remain the existing 2D image-plane measurement. This deployment work does not change that calculation.
