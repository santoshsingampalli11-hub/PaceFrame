import { ErrorNotice } from "../components/ErrorNotice";
import { OriginalVideoFrameViewer } from "../components/OriginalVideoFrameViewer";
import { OriginalVideoPlayer } from "../components/OriginalVideoPlayer";
import { PoseReviewPanel } from "../components/PoseReviewPanel";
import { useDeliverySession } from "./useDeliverySession";

export function ReviewPage() {
  const { session, error, loading } = useDeliverySession();

  return (
    <>
      <h1>Video & Pose Review</h1>
      {loading ? <p role="status">Loading session…</p> : null}
      <ErrorNotice message={error} />
      {session ? (
        <div className="workspace">
          <div>
            <p className="hint">
              Watch the original video and locate the approximate delivery moment. Then inspect a decoded frame for
              precise manual annotation. Playback time is not a frame index.
            </p>
            <OriginalVideoPlayer
              sessionId={session.session_id}
              frameWidth={session.width}
              frameHeight={session.height}
            />
            <h2>Exact frame review</h2>
            <p className="hint">
              Original frames have no pose drawing. Overlay images appear only for the indexes you list before starting a
              review. A detected pose is not localization accuracy.
            </p>
            <OriginalVideoFrameViewer
              sessionId={session.session_id}
              frameCount={session.decoded_frame_count}
              frameWidth={session.width}
              frameHeight={session.height}
            />
          </div>
          <PoseReviewPanel sessionId={session.session_id} decodedFrameCount={session.decoded_frame_count} />
        </div>
      ) : null}
    </>
  );
}
