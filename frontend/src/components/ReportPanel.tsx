import { useEffect, useState } from "react";
import {
  ApiError,
  getMeasurement,
  getMeasurementReport,
  getPoseReview,
  getPoseReviewReport,
  getSessionLabels,
} from "../api/client";
import type { PoseReviewReport, SessionLabels, SessionResponse, StoredMeasurement } from "../api/types";
import { MeasurementExportButtons } from "./MeasurementExportButtons";

type ReportPanelProps = {
  session: SessionResponse;
};

export function ReportPanel({ session }: ReportPanelProps) {
  const [labels, setLabels] = useState<SessionLabels | null>(null);
  const [measurement, setMeasurement] = useState<StoredMeasurement | null>(null);
  const [pose, setPose] = useState<PoseReviewReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const storedLabels = await getSessionLabels(session.session_id);
        const job = await getMeasurement(session.session_id);
        const review = await getPoseReview(session.session_id).catch((caught: unknown) => {
          if (caught instanceof ApiError && caught.status === 404) return null;
          throw caught;
        });
        if (!active) return;
        setLabels(storedLabels);
        if (job?.status === "completed") {
          const report = await getMeasurementReport(session.session_id);
          if (active) setMeasurement(report.report);
        }
        if (review?.status === "completed") {
          const summary = await getPoseReviewReport(session.session_id);
          if (active) setPose(summary);
        }
        if (active) setError(null);
      } catch (caught: unknown) {
        if (!active) return;
        setError(caught instanceof ApiError ? caught.message : "The report could not be loaded.");
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [session.session_id]);

  const ffcText =
    measurement?.ffc.status === "available" && measurement.ffc.angle_degrees !== null
      ? `${measurement.ffc.angle_degrees.toFixed(2)}°`
      : "Unavailable";
  const releaseText =
    measurement?.release.status === "available" && measurement.release.angle_degrees !== null
      ? `${measurement.release.angle_degrees.toFixed(2)}°`
      : "Unavailable";

  return (
    <section aria-label="Analysis report">
      <p className="hint">
        This report repeats stored inspection, manual labels, and 2D knee results. It is not a 3D laboratory record and
        not an injury conclusion. A file hash does not prove the recording is suitable.
      </p>
      {error ? <p role="alert">{error}</p> : null}
      <div className="report-grid">
        <section className="panel">
          <h2>Session</h2>
          <dl className="facts">
            <dt>Bowler</dt>
            <dd>{session.bowler_id}</dd>
            <dt>Delivery</dt>
            <dd>{session.delivery_id}</dd>
            <dt>Session</dt>
            <dd>{session.session_id}</dd>
            <dt>Stored file</dt>
            <dd>{session.video_filename}</dd>
            <dt>Resolution</dt>
            <dd>
              {session.width} × {session.height}
            </dd>
            <dt>Encoded FPS</dt>
            <dd>{session.encoded_fps}</dd>
            <dt>Decoded frames</dt>
            <dd>{session.decoded_frame_count}</dd>
            <dt>Orientation</dt>
            <dd>{session.orientation}</dd>
          </dl>
        </section>
        <section className="panel">
          <h2>Manual events</h2>
          <dl className="facts">
            <dt>BFC frame</dt>
            <dd>{labels ? (labels.bfc_frame ?? "not marked") : "Unavailable"}</dd>
            <dt>FFC frame</dt>
            <dd>{labels?.ffc_frame ?? "Unavailable"}</dd>
            <dt>Release frame</dt>
            <dd>{labels?.release_frame ?? "Unavailable"}</dd>
            <dt>Front leg</dt>
            <dd>{labels?.front_leg ?? session.front_leg ?? "Unavailable"}</dd>
          </dl>
        </section>
        <section className="panel">
          <h2>2D front knee</h2>
          <dl className="facts">
            <dt>2D knee at FFC</dt>
            <dd>{ffcText}</dd>
            <dt>2D knee at Release</dt>
            <dd>{releaseText}</dd>
          </dl>
          {measurement ? null : <p>No measurement report is stored yet.</p>}
        </section>
        <section className="panel">
          <h2>Provenance</h2>
          <dl className="facts">
            <dt>Label provenance</dt>
            <dd>{labels?.annotation_provenance ?? "Unavailable"}</dd>
            <dt>Label bytes verified</dt>
            <dd>{labels ? (labels.annotation_byte_identity_verified ? "Yes" : "No") : "Unavailable"}</dd>
            <dt>Pose frames with a detection</dt>
            <dd>{pose?.pose_frames ?? "Unavailable"}</dd>
            <dt>Pose frames without a detection</dt>
            <dd>{pose?.missing_pose_count ?? "Unavailable"}</dd>
          </dl>
        </section>
      </div>
      {measurement ? (
        <ul>
          {measurement.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
          {measurement.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
      <MeasurementExportButtons
        sessionId={session.session_id}
        bowlerId={session.bowler_id}
        deliveryId={session.delivery_id}
        measurement={measurement}
      />
    </section>
  );
}
