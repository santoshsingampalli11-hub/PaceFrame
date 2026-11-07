import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getMeasurement, getMeasurementReport, getSessionLabels, startMeasurement } from "../api/client";
import type { KneeAngleResult, MeasurementJobState, SessionLabels, SessionResponse, StoredMeasurement } from "../api/types";
import { MeasurementExportButtons } from "./MeasurementExportButtons";

type KneeMeasurementPanelProps = {
  session: SessionResponse;
};

export function KneeMeasurementPanel({ session }: KneeMeasurementPanelProps) {
  const [labels, setLabels] = useState<SessionLabels | null>(null);
  const [job, setJob] = useState<MeasurementJobState | null>(null);
  const [result, setResult] = useState<StoredMeasurement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [confirmNow, setConfirmNow] = useState(false);
  const gaps = missingPrerequisites(labels);
  const active = job?.status === "queued" || job?.status === "running" || starting;
  const finished = job?.status === "completed" && result !== null;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      let keep = false;
      try {
        const stored = await getSessionLabels(session.session_id);
        if (cancelled) return;
        setLabels((current) => (JSON.stringify(current) === JSON.stringify(stored) ? current : stored));
        const current = await getMeasurement(session.session_id);
        if (cancelled) return;
        setJob((previous) => (JSON.stringify(previous) === JSON.stringify(current) ? previous : current));
        if (current?.status === "completed") {
          const report = await getMeasurementReport(session.session_id);
          if (!cancelled) {
            setResult((previous) =>
              JSON.stringify(previous) === JSON.stringify(report.report) ? previous : report.report,
            );
          }
        } else {
          setResult(null);
          keep = current?.status === "queued" || current?.status === "running";
        }
      } catch (caught: unknown) {
        if (cancelled) return;
        setError(caught instanceof ApiError ? caught.message : "The measurement could not be loaded.");
        return;
      }
      if (keep && !cancelled) {
        timer = setTimeout(() => {
          void tick();
        }, 2000);
      }
    }

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [session.session_id, starting]);

  async function onStart() {
    if (!confirmNow || gaps.length > 0 || active || finished) return;
    setStarting(true);
    setError(null);
    try {
      await startMeasurement(session.session_id, true);
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : "The measurement could not be started.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <section className="panel" aria-label="Knee kinematics">
      <h2>2D front-knee angle</h2>
      <p className="hint">
        These are image-plane angles at the manual FFC and Release frames. They are not 3D laboratory angles, technique
        scores, or injury estimates. Visibility is a model score, not accuracy. An unavailable result is not zero degrees.
      </p>
      {error ? <p role="alert">{error}</p> : null}
      <dl className="facts">
        <dt>Session</dt>
        <dd>{session.session_id}</dd>
        <dt>Bowler</dt>
        <dd>{session.bowler_id}</dd>
        <dt>Delivery</dt>
        <dd>{session.delivery_id}</dd>
        <dt>Saved FFC frame</dt>
        <dd>{labels?.ffc_frame ?? "Unavailable"}</dd>
        <dt>Saved Release frame</dt>
        <dd>{labels?.release_frame ?? "Unavailable"}</dd>
        <dt>Front leg</dt>
        <dd>{labels?.front_leg ?? "Unavailable"}</dd>
        <dt>Front leg confirmed</dt>
        <dd>{labels ? (labels.confirm_front_leg ? "Yes" : "No") : "Unavailable"}</dd>
        <dt>Label link recorded</dt>
        <dd>{labels ? (labels.confirm_label_link ? "Yes" : "No") : "Unavailable"}</dd>
        <dt>Measurement status</dt>
        <dd>{job ? `${job.status}. ${job.message}` : "not started"}</dd>
        <dt>Video identity</dt>
        <dd>{result?.video_sha256 ?? "Unavailable"}</dd>
      </dl>
      {gaps.length > 0 ? (
        <>
          <ul>
            {gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
          <p>
            <Link to={`/sessions/${session.session_id}/events`}>Open Event Annotation</Link>
          </p>
        </>
      ) : null}
      {!finished && gaps.length === 0 ? (
        <label htmlFor="confirm-measure-link">
          <input
            id="confirm-measure-link"
            type="checkbox"
            checked={confirmNow}
            onChange={(event) => setConfirmNow(event.target.checked)}
          />
          I confirm again that these saved labels belong to this video
        </label>
      ) : null}
      {!finished ? (
        <button type="button" onClick={() => void onStart()} disabled={gaps.length > 0 || !confirmNow || active}>
          {active ? "Measurement in progress…" : "Start measurement"}
        </button>
      ) : (
        <p role="status">A measurement report is already stored. Another job was not started.</p>
      )}
      {result ? (
        <div className="metric-grid">
          <AngleCard title="Front-foot contact" frame={result.ffc_frame} angle={result.ffc} />
          <AngleCard title="Ball release" frame={result.release_frame} angle={result.release} />
        </div>
      ) : null}
      {result ? (
        <ul>
          {(result.warnings ?? []).map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
          {(result.limitations ?? []).map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      ) : null}
      <MeasurementExportButtons
        sessionId={session.session_id}
        bowlerId={session.bowler_id}
        deliveryId={session.delivery_id}
        measurement={result}
      />
    </section>
  );
}

export function missingPrerequisites(labels: SessionLabels | null): string[] {
  if (!labels) return ["Saved labels were not found."];
  const gaps: string[] = [];
  if (labels.ffc_frame === null) gaps.push("FFC is not saved.");
  if (labels.release_frame === null) gaps.push("Release is not saved.");
  if (
    labels.ffc_frame !== null &&
    labels.release_frame !== null &&
    labels.ffc_frame >= labels.release_frame
  ) {
    gaps.push("FFC must be earlier than Release.");
  }
  if (labels.front_leg !== "left" && labels.front_leg !== "right") gaps.push("Anatomical front leg is not saved.");
  if (!labels.confirm_front_leg) gaps.push("Front-leg confirmation was not recorded.");
  if (!labels.confirm_label_link) gaps.push("The video-label confirmation was not recorded.");
  return gaps;
}

function AngleCard({ title, frame, angle }: { title: string; frame: number | null; angle: KneeAngleResult }) {
  const value = angle.status === "available" && angle.angle_degrees !== null ? `${angle.angle_degrees.toFixed(2)}°` : "Unavailable";
  return (
    <article className="panel">
      <h3>{title}</h3>
      <p>Frame: {frame ?? "Unavailable"}</p>
      <p className="metric">{value}</p>
      <p>Status: {angle.status}</p>
      <p>Review: {angle.review_status || "Unavailable"}</p>
      {angle.reason ? <p>{angle.reason}</p> : null}
      <ul>
        {(angle.evidence ?? []).map((item) => (
          <li key={`${item.role}-${item.name}`}>
            {item.role} {item.name}: {item.available ? "present" : "missing"}
            {item.visibility === null ? "" : `, visibility ${item.visibility} (not accuracy)`}
          </li>
        ))}
      </ul>
      {(angle.warnings ?? []).map((warning) => (
        <p key={warning}>{warning}</p>
      ))}
    </article>
  );
}
