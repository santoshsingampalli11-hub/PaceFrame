/** Fields returned by GET /api/sessions/{session_id} and POST /api/sessions. */

export type SessionResponse = {
  session_id: string;
  bowler_id: string;
  delivery_id: string;
  video_filename: string;
  video_sha256: string;
  width: number;
  height: number;
  encoded_fps: number;
  decoded_frame_count: number;
  orientation: string;
  status: string;
  front_leg: string | null;
  camera_side_on_confirmed: boolean;
  full_body_visibility_confirmed: boolean;
  scientific_caveat: string;
};

export type HealthResponse = {
  status: string;
};

export type PoseReviewStatus = {
  session_id: string;
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  message: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  review_frames: number[];
  scientific_caveat: string;
};

export type PoseReviewReport = {
  session_id: string;
  job_id: string;
  status: string;
  report_text: string;
  pose_frames: number | null;
  decoded_frame_count: number | null;
  missing_pose_count: number | null;
  scientific_caveat: string;
  limitations: string[];
  overlay_frames: number[];
};

export type SessionLabels = {
  session_id: string;
  bowler_id: string;
  delivery_id: string;
  video_filename: string;
  bfc_frame: number | null;
  ffc_frame: number | null;
  release_frame: number | null;
  labeler: string;
  notes: string;
  front_leg: string;
  confirm_front_leg: boolean;
  confirm_label_link: boolean;
  annotation_provenance: string;
  annotation_byte_identity_verified: boolean;
  scientific_caveat: string;
};

export type SaveLabelsInput = {
  bfc_frame: number | null;
  ffc_frame: number;
  release_frame: number;
  front_leg: "left" | "right";
  confirm_front_leg: boolean;
  confirm_label_link: boolean;
  labeler: string;
  notes: string;
};

export type LandmarkCalculationPoint = {
  role: string;
  name: string;
  x_normalized: number;
  y_normalized: number;
  x_px: number;
  y_px: number;
  visibility: number | null;
  presence: number | null;
};

export type CalculationEvidence = {
  schema_version: string;
  calculation: string;
  definition: string;
  frame_index: number;
  frame_timestamp_seconds: number;
  image_width_px: number;
  image_height_px: number;
  front_leg: string;
  landmark_names: string[];
  hip: LandmarkCalculationPoint;
  knee: LandmarkCalculationPoint;
  ankle: LandmarkCalculationPoint;
  angle_degrees: number;
  origin: string;
  positive_x: string;
  positive_y: string;
  coordinate_unit: string;
  video_sha256: string | null;
};

export type KneeAngleResult = {
  frame_index: number | null;
  angle_degrees: number | null;
  status: string;
  reason: string;
  review_status: string;
  warnings: string[];
  evidence: Array<{
    role: string;
    name: string;
    available: boolean;
    visibility: number | null;
    presence: number | null;
  }>;
  calculation_evidence?: CalculationEvidence | null;
};

export type StoredMeasurement = {
  bowler_id: string;
  delivery_id: string;
  front_leg: string | null;
  ffc_frame: number | null;
  release_frame: number | null;
  ffc: KneeAngleResult;
  release: KneeAngleResult;
  warnings: string[];
  limitations: string[];
  annotation_provenance: string;
  annotation_byte_identity_verified: boolean;
  video_sha256: string;
};

export type MeasurementJobState = {
  session_id: string;
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  message: string;
  scientific_caveat: string;
};

export type MeasurementReportEnvelope = {
  session_id: string;
  job_id: string;
  status: string;
  report: StoredMeasurement;
  scientific_caveat: string;
};

export type CreateSessionInput = {
  video: File;
  bowlerId: string;
  deliveryId: string;
  frontLeg: "" | "left" | "right";
};
