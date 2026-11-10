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
import { ScientificLimitations } from "./LimitationSection";

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

  const byteVerification = labels
    ? labels.annotation_byte_identity_verified
      ? "Verified"
      : "Not verified"
    : "Unavailable";

  return (
    <section aria-label="Analysis report">
      <p className="hint">
        This report repeats stored inspection, manual labels, and 2D knee results. It is not a 3D laboratory record and
        not an injury conclusion. A file hash does not prove the recording is suitable.
      </p>
      {error ? <p role="alert">{error}</p> : null}
      <div className="report-layout">
        <div className="report-primary">
          <section className="panel report-knee">
            <h2>2D Front Knee Kinematics</h2>
            <p className="hint">Image-plane knee angles at human-confirmed bowling events</p>
            <div className="metric-tiles">
              <article className="metric-tile">
                <h3>Front-foot contact (FFC)</h3>
                <p className="metric-value">{ffcText}</p>
                <p className="metric-status">Status: {measurement?.ffc.status ?? "not stored"}</p>
              </article>
              <article className="metric-tile">
                <h3>Ball release</h3>
                <p className="metric-value">{releaseText}</p>
                <p className="metric-status">Status: {measurement?.release.status ?? "not stored"}</p>
              </article>
            </div>
            {measurement ? null : <p>No measurement report is stored yet.</p>}
            <MeasurementExportButtons
              sessionId={session.session_id}
              bowlerId={session.bowler_id}
              deliveryId={session.delivery_id}
              measurement={measurement}
            />
          </section>
          <section className="panel report-events">
            <h2>Manual events</h2>
            <p className="hint">These frame indexes were selected by a person. They are not automatic detections.</p>
            <dl className="facts">
              <dt>BFC frame</dt>
              <dd>{labels ? (labels.bfc_frame ?? "not marked") : "Unavailable"}</dd>
              <dt>FFC frame</dt>
              <dd>{labels?.ffc_frame ?? "Unavailable"}</dd>
              <dt>Release frame</dt>
              <dd>{labels?.release_frame ?? "Unavailable"}</dd>
              <dt>Anatomical front leg</dt>
              <dd>{labels?.front_leg ?? session.front_leg ?? "Unavailable"}</dd>
            </dl>
          </section>
        </div>
        <div className="report-support">
          <section className="panel report-session">
            <h2>Session</h2>
            <dl className="facts">
              <dt>Bowler ID</dt>
              <dd>{session.bowler_id}</dd>
              <dt>Delivery ID</dt>
              <dd>{session.delivery_id}</dd>
              <dt>Session ID</dt>
              <dd className="session-id" title={session.session_id}>
                {session.session_id}
              </dd>
            </dl>
            <details className="session-more">
              <summary>More session details</summary>
              <dl className="facts">
                <dt>Stored filename</dt>
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
            </details>
          </section>
          <section className="panel report-provenance">
            <h2>Provenance</h2>
            <dl className="facts">
              <dt>Label provenance</dt>
              <dd>{labels?.annotation_provenance ?? "Unavailable"}</dd>
              <dt>Label byte verification</dt>
              <dd>{byteVerification}</dd>
              <dt>Pose frames with a detection</dt>
              <dd>{pose?.pose_frames ?? "Unavailable"}</dd>
              <dt>Pose frames without a detection</dt>
              <dd>{pose?.missing_pose_count ?? "Unavailable"}</dd>
            </dl>
          </section>
        </div>
      </div>
      {measurement ? <ScientificLimitations measurement={measurement} /> : null}
    </section>
  );
}
