import { FormEvent, useEffect, useState } from "react";
import {
  ApiError,
  getPoseReview,
  getPoseReviewReport,
  poseReviewFrameUrl,
  startPoseReview,
} from "../api/client";
import type { PoseReviewReport, PoseReviewStatus } from "../api/types";
import { ErrorNotice } from "./ErrorNotice";

const POLL_MS = 2000;
const MAX_FRAMES = 8;

type PoseReviewPanelProps = {
  sessionId: string;
  decodedFrameCount: number;
};

export function PoseReviewPanel({ sessionId, decodedFrameCount }: PoseReviewPanelProps) {
  const [status, setStatus] = useState<PoseReviewStatus | null>(null);
  const [report, setReport] = useState<PoseReviewReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [frameText, setFrameText] = useState("");
  const [frameError, setFrameError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [frameIndex, setFrameIndex] = useState<number | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [pollToken, setPollToken] = useState(0);

  const active = status?.status === "queued" || status?.status === "running";

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      let keepPolling = false;
      try {
        const next = await getPoseReview(sessionId);
        if (cancelled) return;
        setStatus((current) => (JSON.stringify(current) === JSON.stringify(next) ? current : next));
        setError(null);
        if (next.status === "completed") {
          const loaded = await getPoseReviewReport(sessionId);
          if (cancelled) return;
          setReport(loaded);
          const frames = overlayList(loaded.overlay_frames);
          setFrameIndex((current) => (current !== null && frames.includes(current) ? current : (frames[0] ?? null)));
        } else {
          setReport(null);
          keepPolling = next.status === "queued" || next.status === "running";
        }
      } catch (caught: unknown) {
        if (cancelled) return;
        if (caught instanceof ApiError && caught.status === 404) {
          setStatus(null);
          setReport(null);
          return;
        }
        setError(caught instanceof ApiError ? caught.message : "Pose review status could not be loaded.");
        return;
      }
      if (keepPolling && !cancelled) {
        timer = setTimeout(() => {
          void tick();
        }, POLL_MS);
      }
    }

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [sessionId, pollToken]);

  async function onStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (starting || active) return;
    const parsed = parseFrames(frameText);
    if (parsed.error) {
      setFrameError(parsed.error);
      return;
    }
    setFrameError(null);
    setError(null);
    setStarting(true);
    try {
      await startPoseReview(sessionId, parsed.frames);
      setReport(null);
      setFrameIndex(null);
      setPollToken((value) => value + 1);
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : "Pose review could not be started.");
    } finally {
      setStarting(false);
    }
  }

  const overlays = overlayList(report?.overlay_frames);
  const current = frameIndex !== null && overlays.includes(frameIndex) ? frameIndex : overlays[0] ?? null;
  const currentPosition = current === null ? -1 : overlays.indexOf(current);

  return (
    <section className="panel">
      <h2>Pose review</h2>
      <p className="hint">
        This runs the existing MediaPipe video-mode review. A detected pose is not biomechanical accuracy, not bowler
        identity, and not a joint angle. Only the frame indexes you list are exported as overlay images. This is not a
        full-video scrubber, and it does not choose BFC, FFC, or release.
      </p>
      <p>
        Status: <strong>{status ? status.status : "Pose review not started."}</strong>
        {status?.message ? ` — ${status.message}` : ""}
      </p>
      <ErrorNotice message={error} />
      <form onSubmit={onStart}>
        <label htmlFor="review-frames">
          Overlay frame indexes
          <input
            id="review-frames"
            value={frameText}
            inputMode="numeric"
            aria-describedby="review-frames-hint"
            onChange={(event) => setFrameText(event.target.value)}
          />
        </label>
        <p id="review-frames-hint" className="hint">
          Optional. Up to {MAX_FRAMES} exact zero-based indexes, separated by commas. This video decoded{" "}
          {decodedFrameCount} frames, numbered 0 to {Math.max(decodedFrameCount - 1, 0)}. Leave blank to run the
          diagnostic without images.
        </p>
        {frameError ? <p className="field-error">{frameError}</p> : null}
        <button type="submit" disabled={starting || active}>
          {starting || active ? "Pose review in progress…" : "Start pose review"}
        </button>
      </form>
      {report ? <PoseReport report={report} /> : null}
      {report && overlays.length === 0 ? (
        <p>No overlay images were exported. List frame indexes before starting a review if you want images.</p>
      ) : null}
      {report && current !== null ? (
        <FrameViewer
          sessionId={sessionId}
          frames={overlays}
          current={current}
          failed={imageFailed}
          onSelect={(index) => {
            setFrameIndex(index);
            setImageFailed(false);
          }}
          onError={() => setImageFailed(true)}
          position={currentPosition}
        />
      ) : null}
    </section>
  );
}

function PoseReport({ report }: { report: PoseReviewReport }) {
  return (
    <div>
      <h3>Diagnostic report</h3>
      <p className="hint">{report.scientific_caveat}</p>
      <dl className="facts">
        <dt>Decoded frames</dt>
        <dd>{report.decoded_frame_count ?? "unavailable"}</dd>
        <dt>Frames with a detected pose</dt>
        <dd>{report.pose_frames ?? "unavailable"}</dd>
        <dt>Frames without a detected pose</dt>
        <dd>{report.missing_pose_count ?? "unavailable"}</dd>
      </dl>
      <p className="hint">These counts are detections. They are not an accuracy percentage.</p>
      <ul>
        {report.limitations.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <pre className="report-text">{report.report_text}</pre>
    </div>
  );
}

function FrameViewer({
  sessionId,
  frames,
  current,
  position,
  failed,
  onSelect,
  onError,
}: {
  sessionId: string;
  frames: number[];
  current: number;
  position: number;
  failed: boolean;
  onSelect: (index: number) => void;
  onError: () => void;
}) {
  return (
    <div>
      <h3>Exported overlay</h3>
      <p className="hint">
        Frame {current}. The image is the raw MediaPipe overlay saved for this index. Points are not moved onto the
        body, and foot corrections are not applied.
      </p>
      {failed ? <p role="alert">The overlay image for frame {current} was not found.</p> : null}
      <div className="overlay-stage">
        <img
          className="overlay-image"
          src={poseReviewFrameUrl(sessionId, current)}
          alt={`Raw pose overlay for decoded frame ${current}`}
          onError={onError}
        />
      </div>
      {failed ? null : (
        <p className="hint">
          <a href={poseReviewFrameUrl(sessionId, current)} target="_blank" rel="noreferrer">
            Open frame {current} overlay at full size
          </a>
        </p>
      )}
      <div className="frame-controls">
        <button type="button" disabled={position <= 0} onClick={() => onSelect(frames[position - 1])}>
          Previous exported frame
        </button>
        <label htmlFor="frame-select">
          Exported frame
          <select
            id="frame-select"
            value={String(current)}
            onChange={(event) => onSelect(Number(event.target.value))}
          >
            {frames.map((index) => (
              <option key={index} value={index}>
                {index}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={position < 0 || position >= frames.length - 1}
          onClick={() => onSelect(frames[position + 1])}
        >
          Next exported frame
        </button>
      </div>
    </div>
  );
}

function overlayList(frames: number[] | undefined): number[] {
  return Array.isArray(frames) ? frames : [];
}

function parseFrames(text: string): { frames: number[]; error: string | null } {
  const trimmed = text.trim();
  if (!trimmed) return { frames: [], error: null };
  const parts = trimmed.split(",").map((part) => part.trim());
  const frames: number[] = [];
  for (const part of parts) {
    if (!/^\d+$/.test(part)) {
      return { frames: [], error: "Frame indexes must be non-negative whole numbers." };
    }
    frames.push(Number(part));
  }
  if (frames.length > MAX_FRAMES) {
    return { frames: [], error: `At most ${MAX_FRAMES} frames can be requested.` };
  }
  if (new Set(frames).size !== frames.length) {
    return { frames: [], error: "Do not repeat a frame index." };
  }
  return { frames, error: null };
}
