import type {
  CreateSessionInput,
  HealthResponse,
  PoseReviewReport,
  PoseReviewStatus,
  MeasurementJobState,
  MeasurementReportEnvelope,
  SaveLabelsInput,
  SessionLabels,
  SessionResponse,
} from "./types";

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

export const MAX_UPLOAD_BYTES = 80 * 1024 * 1024;

const PATH_HINT = /[A-Za-z]:\\|\\\\|\/Users\/|\/home\/|\\Users\\/;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await request("/health");
  return readJson(response, isHealth);
}

export async function createSession(input: CreateSessionInput): Promise<SessionResponse> {
  const body = new FormData();
  body.append("video", input.video, input.video.name);
  body.append("bowler_id", input.bowlerId.trim());
  body.append("delivery_id", input.deliveryId.trim());
  if (input.frontLeg) {
    body.append("front_leg", input.frontLeg);
  }
  const response = await request("/api/sessions", { method: "POST", body });
  return readJson(response, isSession);
}

export async function startMeasurement(sessionId: string, confirmLabelLink: boolean): Promise<{ status: string }> {
  const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}/measure`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm_label_link: confirmLabelLink }),
  });
  return readJson(response, isStartedJob);
}

export async function getMeasurement(sessionId: string): Promise<MeasurementJobState | null> {
  try {
    const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}/measure`);
    return readJson(response, isMeasurementJob);
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function getMeasurementReport(sessionId: string): Promise<MeasurementReportEnvelope> {
  const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}/report`);
  return readJson(response, isMeasurementReport);
}

export async function getSessionLabels(sessionId: string): Promise<SessionLabels | null> {
  try {
    const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}/labels`);
    return readJson(response, isSessionLabels);
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function saveSessionLabels(sessionId: string, input: SaveLabelsInput): Promise<SessionLabels> {
  const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}/labels`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...input, replace_existing: false }),
  });
  return readJson(response, isSessionLabels);
}

export async function getSession(sessionId: string): Promise<SessionResponse> {
  const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}`);
  return readJson(response, isSession);
}

export async function startPoseReview(sessionId: string, reviewFrames: number[]): Promise<{ status: string }> {
  const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}/pose-review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ review_frames: reviewFrames }),
  });
  return readJson(response, isStartedJob);
}

export async function getPoseReview(sessionId: string): Promise<PoseReviewStatus> {
  const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}/pose-review`);
  return readJson(response, isPoseStatus);
}

export async function getPoseReviewReport(sessionId: string): Promise<PoseReviewReport> {
  const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}/pose-review/report`);
  return readJson(response, isPoseReport);
}

export async function getOriginalFrame(sessionId: string, frameIndex: number, signal?: AbortSignal): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE_URL}/api/sessions/${encodeURIComponent(sessionId)}/video/frames/${frameIndex}`,
      { signal },
    );
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(0, "The analysis server is not reachable.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  const type = response.headers.get("content-type") ?? "";
  if (!type.startsWith("image/jpeg")) {
    throw new ApiError(response.status, "The server did not return a video frame.");
  }
  return response.blob();
}

export function poseReviewFrameUrl(sessionId: string, frameIndex: number): string {
  return `${API_BASE_URL}/api/sessions/${encodeURIComponent(sessionId)}/pose-review/frames/${frameIndex}`;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(0, "The analysis server is not reachable.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  return response;
}

async function errorMessage(response: Response): Promise<string> {
  const fallback = fallbackMessage(response.status);
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === "object" && "detail" in payload) {
      const detail = (payload as { detail: unknown }).detail;
      if (typeof detail === "string" && detail.trim() && !PATH_HINT.test(detail)) {
        return detail.trim();
      }
    }
  } catch {
    return fallback;
  }
  return fallback;
}

function fallbackMessage(status: number): string {
  if (status === 400) return "The server rejected this request.";
  if (status === 404) return "That session was not found.";
  if (status === 413) return "The upload is larger than the server limit.";
  if (status === 415) return "This file type is not supported.";
  if (status === 422) return "The form is missing a required field or has an invalid value.";
  if (status >= 500) return "The server could not complete this request.";
  return "The server returned an unexpected response.";
}

async function readJson<T>(response: Response, guard: (value: unknown) => value is T): Promise<T> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError(response.status, "The server returned an unexpected response.");
  }
  if (!guard(payload)) {
    throw new ApiError(response.status, "The server returned an unexpected response.");
  }
  return payload;
}

function isMeasurementJob(value: unknown): value is MeasurementJobState {
  if (!value || typeof value !== "object") return false;
  const job = value as MeasurementJobState;
  return typeof job.status === "string" && typeof job.message === "string" && typeof job.job_id === "string";
}

function isAngle(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const angle = value as { status?: unknown; angle_degrees?: unknown };
  return typeof angle.status === "string" && (angle.angle_degrees === null || typeof angle.angle_degrees === "number");
}

function isMeasurementReport(value: unknown): value is MeasurementReportEnvelope {
  if (!value || typeof value !== "object") return false;
  const envelope = value as MeasurementReportEnvelope;
  return Boolean(envelope.report && isAngle(envelope.report.ffc) && isAngle(envelope.report.release));
}

function isSessionLabels(value: unknown): value is SessionLabels {
  if (!value || typeof value !== "object") return false;
  const labels = value as SessionLabels;
  return (
    typeof labels.session_id === "string" &&
    typeof labels.ffc_frame === "number" &&
    typeof labels.release_frame === "number" &&
    (labels.bfc_frame === null || typeof labels.bfc_frame === "number") &&
    typeof labels.front_leg === "string" &&
    typeof labels.confirm_front_leg === "boolean" &&
    typeof labels.confirm_label_link === "boolean" &&
    typeof labels.annotation_byte_identity_verified === "boolean" &&
    typeof labels.scientific_caveat === "string"
  );
}

function isStartedJob(value: unknown): value is { status: string } {
  return Boolean(value && typeof value === "object" && typeof (value as { status: unknown }).status === "string");
}

function isPoseStatus(value: unknown): value is PoseReviewStatus {
  if (!value || typeof value !== "object") return false;
  const status = value as PoseReviewStatus;
  return (
    typeof status.job_id === "string" &&
    typeof status.status === "string" &&
    typeof status.message === "string" &&
    Array.isArray(status.review_frames)
  );
}

function isPoseReport(value: unknown): value is PoseReviewReport {
  if (!value || typeof value !== "object") return false;
  const report = value as PoseReviewReport;
  return typeof report.report_text === "string" && Array.isArray(report.limitations);
}

function isHealth(value: unknown): value is HealthResponse {
  return Boolean(value && typeof value === "object" && typeof (value as HealthResponse).status === "string");
}

function isSession(value: unknown): value is SessionResponse {
  if (!value || typeof value !== "object") return false;
  const session = value as SessionResponse;
  return (
    typeof session.session_id === "string" &&
    typeof session.bowler_id === "string" &&
    typeof session.delivery_id === "string" &&
    typeof session.video_filename === "string" &&
    typeof session.width === "number" &&
    typeof session.height === "number" &&
    typeof session.encoded_fps === "number" &&
    typeof session.decoded_frame_count === "number" &&
    typeof session.orientation === "string" &&
    typeof session.status === "string" &&
    typeof session.scientific_caveat === "string" &&
    typeof session.camera_side_on_confirmed === "boolean" &&
    typeof session.full_body_visibility_confirmed === "boolean"
  );
}
