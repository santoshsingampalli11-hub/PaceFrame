import { FormEvent, KeyboardEvent, forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { ApiError, getOriginalFrame } from "../api/client";
import { cachedFrameUrl, storeFrameUrl } from "./frameImageCache";

export type OriginalFrameViewerHandle = {
  goTo: (index: number) => void;
};

const LARGE_STEP = 10;

type ShownFrame = {
  sessionId: string;
  index: number;
  url: string;
};

type OriginalVideoFrameViewerProps = {
  sessionId: string;
  frameCount: number;
  frameWidth?: number;
  frameHeight?: number;
  onDisplayedFrame?: (index: number | null) => void;
};

export const OriginalVideoFrameViewer = forwardRef<OriginalFrameViewerHandle, OriginalVideoFrameViewerProps>(
  function OriginalVideoFrameViewer({ sessionId, frameCount, frameWidth, frameHeight, onDisplayedFrame }, ref) {
  const lastIndex = Math.max(frameCount - 1, 0);
  const [requested, setRequested] = useState(0);
  const [slider, setSlider] = useState(0);
  const [shown, setShown] = useState<ShownFrame | null>(null);
  const [loading, setLoading] = useState(frameCount > 0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [jumpError, setJumpError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [jumpText, setJumpText] = useState("0");
  const sliderTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const viewerRef = useRef<HTMLElement | null>(null);
  const visible = shown?.sessionId === sessionId ? shown : null;

  useEffect(() => {
    if (frameCount < 1) return undefined;
    const hit = cachedFrameUrl(sessionId, requested);
    if (hit) {
      setShown({ sessionId, index: requested, url: hit });
      setLoading(false);
      setLoadError(null);
      return undefined;
    }
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    getOriginalFrame(sessionId, requested, controller.signal)
      .then((blob) => {
        if (cancelled) return;
        const url = storeFrameUrl(sessionId, requested, blob);
        setShown({ sessionId, index: requested, url });
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (cancelled || (caught instanceof DOMException && caught.name === "AbortError")) return;
        setLoading(false);
        setLoadError(caught instanceof ApiError ? caught.message : "The frame could not be loaded.");
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [sessionId, requested, frameCount, attempt]);

  useEffect(() => {
    return () => {
      if (sliderTimer.current) clearTimeout(sliderTimer.current);
    };
  }, []);

  const goTo = useCallback(
    (index: number) => {
      const next = Math.min(Math.max(index, 0), lastIndex);
      if (sliderTimer.current) clearTimeout(sliderTimer.current);
      setSlider(next);
      setJumpText(String(next));
      setJumpError(null);
      if (shown?.sessionId !== sessionId || shown.index !== next) {
        setLoading(true);
        onDisplayedFrame?.(null);
      }
      setRequested(next);
    },
    [lastIndex, onDisplayedFrame, sessionId, shown],
  );

  useImperativeHandle(ref, () => ({ goTo }), [goTo]);

  function onSlider(value: number) {
    setSlider(value);
    setJumpText(String(value));
    if (sliderTimer.current) clearTimeout(sliderTimer.current);
    sliderTimer.current = setTimeout(() => {
      setJumpError(null);
      setRequested(value);
    }, 200);
  }

  function onJump(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^\d+$/.test(jumpText.trim())) {
      setJumpError("Enter a whole frame number from 0 to " + lastIndex + ".");
      return;
    }
    const index = Number(jumpText);
    if (index > lastIndex) {
      setJumpError("That frame is past the last decoded frame.");
      return;
    }
    setJumpError(null);
    goTo(index);
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    const target = event.target;
    if (
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement
    ) {
      return;
    }
    const step = event.shiftKey ? LARGE_STEP : 1;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      goTo(requested - step);
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      goTo(requested + step);
    }
    if (event.key === "Home") {
      event.preventDefault();
      goTo(0);
    }
    if (event.key === "End") {
      event.preventDefault();
      goTo(lastIndex);
    }
  }

  const settled = visible !== null && visible.index === requested && !loading && loadError === null;

  useEffect(() => {
    onDisplayedFrame?.(settled && visible ? visible.index : null);
  }, [settled, visible, onDisplayedFrame]);

  if (frameCount < 1) {
    return <p role="alert">This session has no decoded frames to show.</p>;
  }

  const status =
    loading && visible && visible.index !== requested
      ? `Showing frame ${visible.index} — loading frame ${requested}`
      : loading
        ? `Loading frame ${requested}…`
        : visible && visible.index === requested
          ? `Showing frame ${visible.index}`
          : visible
            ? `Showing frame ${visible.index} — requested frame ${requested} is not displayed`
            : "No frame is shown.";

  return (
    <section
      className="panel"
      ref={viewerRef}
      tabIndex={0}
      onKeyDown={onKeyDown}
      aria-label="Original video frames"
    >
      <h2>Original frames</h2>
      <p className="hint">
        This clip has {frameCount} decoded frames, numbered 0 to {lastIndex}. This is the decoded video image with no
        pose overlay. Encoded FPS is not a capture clock. Pose overlays, when a review exported them, stay in the pose
        review section and are not available for every frame.
      </p>
      <p className="frame-status" role="status">
        {status}
      </p>
      {loadError ? (
        <p role="alert">
          {loadError.toLowerCase().includes("capacity")
            ? visible
              ? `The frame decoder is busy. Still showing frame ${visible.index}. That frame is not used for marking until the requested frame loads.`
              : "The frame decoder is busy. No frame is available for marking."
            : visible
              ? `Frame ${requested} did not load. Still showing frame ${visible.index}. ${loadError}`
              : loadError}{" "}
          <button type="button" onClick={() => setAttempt((current) => current + 1)}>
            Retry frame
          </button>
        </p>
      ) : null}
      {jumpError ? <p role="alert">{jumpError}</p> : null}
      <div
        className={loading ? "frame-stage is-loading" : "frame-stage"}
        style={frameWidth && frameHeight ? { aspectRatio: `${frameWidth} / ${frameHeight}` } : undefined}
      >
        {visible ? (
          <img className="frame-image" src={visible.url} alt={`Original decoded frame ${visible.index}`} />
        ) : (
          <p className="hint">Frame not shown.</p>
        )}
      </div>
      <div className="frame-controls">
        <div className="frame-step" role="group" aria-label="Step through decoded frames">
          <button type="button" onClick={() => goTo(requested - LARGE_STEP)} disabled={requested <= 0}>
            Back {LARGE_STEP} frames
          </button>
          <button type="button" onClick={() => goTo(requested - 1)} disabled={requested <= 0}>
            Previous frame
          </button>
          <button type="button" onClick={() => goTo(requested + 1)} disabled={requested >= lastIndex}>
            Next frame
          </button>
          <button type="button" onClick={() => goTo(requested + LARGE_STEP)} disabled={requested >= lastIndex}>
            Forward {LARGE_STEP} frames
          </button>
        </div>
        <form onSubmit={onJump}>
          <label htmlFor="jump-frame">
            Jump to frame
            <input
              id="jump-frame"
              inputMode="numeric"
              value={jumpText}
              onChange={(event) => setJumpText(event.target.value)}
            />
          </label>
          <button type="submit">Show frame</button>
        </form>
      </div>
      <label htmlFor="frame-slider">
        Frame slider, 0 to {lastIndex}
        <input
          id="frame-slider"
          type="range"
          min={0}
          max={lastIndex}
          value={slider}
          onChange={(event) => onSlider(Number(event.target.value))}
        />
      </label>
      <p className="hint">
        When this section is focused: Left and Right arrows move one decoded frame, Shift with an arrow moves{" "}
        {LARGE_STEP}, and Home and End show the first and last frame.
      </p>
    </section>
  );
},
);
