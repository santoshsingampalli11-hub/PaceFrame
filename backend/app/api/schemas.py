"""Typed API responses for the current foundation endpoints."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class RootResponse(BaseModel):
    name: str = Field(examples=["Fast Bowling V1"])
    version: str = Field(examples=["0.1.0"])


class HealthResponse(BaseModel):
    status: str = Field(examples=["healthy"])


class ErrorResponse(BaseModel):
    detail: str


class PoseReviewRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    review_frames: list[StrictInt] = Field(default_factory=list)


class PoseReviewJobResponse(BaseModel):
    session_id: str
    job_id: str
    status: str
    status_path: str
    message: str
    scientific_caveat: str


class PoseReviewStatus(BaseModel):
    session_id: str
    job_id: str
    status: str
    message: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    review_frames: list[int]
    scientific_caveat: str


class PoseReviewReportResponse(BaseModel):
    session_id: str
    job_id: str
    status: str
    report_text: str
    pose_frames: int | None = None
    decoded_frame_count: int | None = None
    missing_pose_count: int | None = None
    scientific_caveat: str
    limitations: list[str]
    overlay_frames: list[int] = Field(default_factory=list)


class SessionLabelsRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    bfc_frame: StrictInt | None = None
    ffc_frame: StrictInt
    release_frame: StrictInt
    front_leg: str
    confirm_front_leg: bool
    confirm_label_link: bool
    labeler: str
    notes: str = ""
    replace_existing: bool = False


class SessionLabelsResponse(BaseModel):
    session_id: str
    bowler_id: str
    delivery_id: str
    video_filename: str
    bfc_frame: int | None
    ffc_frame: int | None
    release_frame: int | None
    labeler: str
    notes: str
    front_leg: str
    confirm_front_leg: bool
    confirm_label_link: bool
    annotation_provenance: str
    annotation_byte_identity_verified: bool
    scientific_caveat: str


class MeasureRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    confirm_label_link: bool


class MeasureJobResponse(BaseModel):
    session_id: str
    job_id: str
    status: str
    status_path: str
    report_path: str
    message: str
    scientific_caveat: str


class MeasureStatus(BaseModel):
    session_id: str
    job_id: str
    status: str
    message: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    scientific_caveat: str


class MeasurementReportResponse(BaseModel):
    session_id: str
    job_id: str
    status: str
    report: dict
    scientific_caveat: str


class SessionResponse(BaseModel):
    session_id: str
    bowler_id: str
    delivery_id: str
    video_filename: str
    video_sha256: str
    width: int
    height: int
    encoded_fps: float
    decoded_frame_count: int
    orientation: str
    status: str
    front_leg: str | None = None
    camera_side_on_confirmed: bool
    full_body_visibility_confirmed: bool
    scientific_caveat: str
