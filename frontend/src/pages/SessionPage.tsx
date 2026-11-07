import { Link } from "react-router-dom";
import { ErrorNotice } from "../components/ErrorNotice";
import { LimitationBanner } from "../components/LimitationBanner";
import { useDeliverySession } from "./useDeliverySession";

export function SessionPage() {
  const { session, error, loading } = useDeliverySession();

  return (
    <>
      <p>
        <Link to="/">Upload another delivery</Link>
      </p>
      {loading ? <p role="status">Loading session…</p> : null}
      <ErrorNotice message={error} />
      {session ? (
        <div className="workspace">
          <section className="panel">
            <h2>Session details</h2>
            <p className="hint">
              Status “{session.status}” means the file was stored and inspected. It does not mean a pose review or knee
              measurement has run. A matching file hash is not scientific suitability.
            </p>
            <dl className="facts">
              <dt>Bowler id</dt>
              <dd>{session.bowler_id}</dd>
              <dt>Delivery id</dt>
              <dd>{session.delivery_id}</dd>
              <dt>Session id</dt>
              <dd>{session.session_id}</dd>
              <dt>Stored filename</dt>
              <dd>{session.video_filename}</dd>
              <dt>Frame size</dt>
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
            <h2>Recording status</h2>
            <ol className="stage" aria-label="Workflow stage">
              <li className="done">Uploaded</li>
              <li className="done">Inspected</li>
              <li className="waiting">Pose review, annotation, and measurement are separate steps</li>
            </ol>
            <LimitationBanner text={session.scientific_caveat} />
            <dl className="facts">
              <dt>Session status</dt>
              <dd>{session.status}</dd>
              <dt>Front leg</dt>
              <dd>{session.front_leg ?? "Not selected"}</dd>
              <dt>Side-on view confirmed</dt>
              <dd>{session.camera_side_on_confirmed ? "Yes" : "No"}</dd>
              <dt>Full body confirmed</dt>
              <dd>{session.full_body_visibility_confirmed ? "Yes" : "No"}</dd>
            </dl>
            <p>
              <Link to={`/sessions/${session.session_id}/review`}>Continue to video and pose review</Link>
            </p>
          </section>
        </div>
      ) : null}
    </>
  );
}
