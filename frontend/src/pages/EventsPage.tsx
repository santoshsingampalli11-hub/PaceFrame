import { useCallback, useRef, useState } from "react";
import { ErrorNotice } from "../components/ErrorNotice";
import { ManualEventAnnotationPanel } from "../components/ManualEventAnnotationPanel";
import { OriginalFrameViewerHandle, OriginalVideoFrameViewer } from "../components/OriginalVideoFrameViewer";
import { useDeliverySession } from "./useDeliverySession";

export function EventsPage() {
  const { session, error, loading } = useDeliverySession();
  const viewerRef = useRef<OriginalFrameViewerHandle>(null);
  const [displayedFrame, setDisplayedFrame] = useState<number | null>(null);
  const onDisplayedFrame = useCallback((index: number | null) => {
    setDisplayedFrame(index);
  }, []);

  return (
    <>
      <h1>Event Annotation</h1>
      {loading ? <p role="status">Loading session…</p> : null}
      <ErrorNotice message={error} />
      {session ? (
        <div className="annotation-layout">
            <OriginalVideoFrameViewer
              ref={viewerRef}
              sessionId={session.session_id}
              frameCount={session.decoded_frame_count}
              frameWidth={session.width}
              frameHeight={session.height}
              onDisplayedFrame={onDisplayedFrame}
            />
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
