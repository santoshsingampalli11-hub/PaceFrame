import { useRef, useState } from "react";
import { OriginalVideoPlayer, type OriginalVideoPlayerHandle } from "../components/OriginalVideoPlayer";
import { approximateReviewFrame } from "../components/approximateFrame";
import { ErrorNotice } from "../components/ErrorNotice";
import { ManualEventAnnotationPanel } from "../components/ManualEventAnnotationPanel";
import { OriginalFrameViewerHandle, OriginalVideoFrameViewer } from "../components/OriginalVideoFrameViewer";
import { useDeliverySession } from "./useDeliverySession";

export function EventsPage() {
  const { session, error, loading } = useDeliverySession();
  const viewerRef = useRef<OriginalFrameViewerHandle>(null);
  const playerRef = useRef<OriginalVideoPlayerHandle>(null);
  const [displayedFrame, setDisplayedFrame] = useState<number | null>(null);
  const [approximateNote, setApproximateNote] = useState<string | null>(null);

  function inspectNearPausedTime() {
    const player = playerRef.current;
    if (!player || !session) return;
    player.pause();
    const seconds = player.getPlaybackSeconds();
    const region =
      seconds === null ? null : approximateReviewFrame(seconds, session.encoded_fps, session.decoded_frame_count);
    if (!region) {
      setApproximateNote("Pause the video after its duration is known. A frame was not guessed.");
      return;
    }
    setApproximateNote(region.label);
    viewerRef.current?.goTo(region.index);
  }

  return (
    <>
      <h1>Event Annotation</h1>
      {loading ? <p role="status">Loading session…</p> : null}
      <ErrorNotice message={error} />
      {session ? (
        <div className="annotation-layout">
          <div>
            <OriginalVideoPlayer
              ref={playerRef}
              sessionId={session.session_id}
              frameWidth={session.width}
              frameHeight={session.height}
            />
            <button type="button" onClick={inspectNearPausedTime}>
              Inspect near paused time
            </button>
            {approximateNote ? <p className="hint">{approximateNote}</p> : null}
            <h2>Exact frame review</h2>
            <p className="hint">
              Inspect a decoded frame before marking an event. Only the frame image that has finished loading can be
              marked.
            </p>
            <OriginalVideoFrameViewer
              ref={viewerRef}
              sessionId={session.session_id}
              frameCount={session.decoded_frame_count}
              frameWidth={session.width}
              frameHeight={session.height}
              onDisplayedFrame={setDisplayedFrame}
            />
          </div>
          <ManualEventAnnotationPanel
            sessionId={session.session_id}
            frameCount={session.decoded_frame_count}
            displayedFrame={displayedFrame}
            knownFrontLeg={session.front_leg}
            onShowFrame={(index) => viewerRef.current?.goTo(index)}
          />
        </div>
      ) : null}
    </>
  );
}
