import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react";
import { originalVideoUrl } from "../api/client";

const SPEEDS = [0.25, 0.5, 1] as const;

type PlaybackState = "loading" | "ready" | "buffering" | "playing" | "paused" | "ended" | "error";

type OriginalVideoPlayerProps = {
  sessionId: string;
  frameWidth?: number;
  frameHeight?: number;
};

export type OriginalVideoPlayerHandle = {
  getPlaybackSeconds: () => number | null;
  pause: () => void;
};

export const OriginalVideoPlayer = forwardRef<OriginalVideoPlayerHandle, OriginalVideoPlayerProps>(
  function OriginalVideoPlayer({ sessionId, frameWidth, frameHeight }, ref) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const paintedAt = useRef(0);
  const [state, setState] = useState<PlaybackState>("loading");
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [playError, setPlayError] = useState<string | null>(null);
  const source = originalVideoUrl(sessionId);
  const aspect = frameWidth && frameHeight ? `${frameWidth} / ${frameHeight}` : "16 / 9";

  useImperativeHandle(ref, () => ({
    getPlaybackSeconds() {
      const video = videoRef.current;
      if (!video || !Number.isFinite(video.duration) || video.duration <= 0) return null;
      const time = video.currentTime;
      if (!Number.isFinite(time) || time < 0) return null;
      return time;
    },
    pause() {
      videoRef.current?.pause();
    },
  }));

  useEffect(() => {
    const video = videoRef.current;
    return () => {
      video?.pause();
    };
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.pause();
    setState("loading");
    setPlayError(null);
    setCurrent(0);
    setDuration(0);
  }, [source]);

  function rememberTime(force: boolean) {
    const video = videoRef.current;
    if (!video) return;
    const now = performance.now();
    if (!force && now - paintedAt.current < 250) return;
    paintedAt.current = now;
    setCurrent(video.currentTime || 0);
  }

  async function play() {
    const video = videoRef.current;
    if (!video || state === "error") return;
    setPlayError(null);
    try {
      await video.play();
    } catch {
      setPlayError("Playback did not start. Press Play again when the video is ready.");
    }
  }

  function pause() {
    videoRef.current?.pause();
  }

  function replay() {
    const video = videoRef.current;
    if (!video || state === "error") return;
    video.currentTime = 0;
    setCurrent(0);
    void play();
  }

  function seek(next: number) {
    const video = videoRef.current;
    if (!video || !Number.isFinite(video.duration)) return;
    video.currentTime = next;
    setCurrent(next);
  }

  function chooseSpeed(next: number) {
    const allowed = SPEEDS.find((value) => value === next);
    if (!allowed) return;
    setSpeed(allowed);
    if (videoRef.current) videoRef.current.playbackRate = allowed;
  }

  const ready = Number.isFinite(duration) && duration > 0 && state !== "error";

  return (
    <section className="panel" aria-label="Original video playback">
      <h2>Video playback</h2>
      <p className="hint">
        Watch the original video and locate the approximate delivery moment. The clock on this player is not a decoded
        frame index and is not used for BFC, FFC, or Release.
      </p>
      <p className="frame-status" role="status">
        {state === "error"
          ? "Playback unavailable"
          : state === "loading"
            ? "Loading video information…"
            : state === "buffering"
              ? "Buffering…"
              : state === "playing"
                ? "Playing"
                : state === "ended"
                  ? "Ended"
                  : state === "paused"
                    ? "Paused"
                    : "Ready"}
        {ready ? ` · ${formatClock(current)} / ${formatClock(duration)}` : ""}
      </p>
      {playError ? <p role="alert">{playError}</p> : null}
      {state === "error" ? (
        <p role="alert">
          This browser could not play the original file. The codec inside the container may be unsupported. Exact frame
          review below is unchanged. The upload was not modified.
        </p>
      ) : null}
      <div className="frame-stage video-stage" style={{ aspectRatio: aspect }}>
        <video
          ref={videoRef}
          className="frame-image"
          src={source}
          preload="metadata"
          controls
          playsInline
          aria-label="Original uploaded video"
          onLoadedMetadata={(event) => {
            const video = event.currentTarget;
            setDuration(Number.isFinite(video.duration) ? video.duration : 0);
            video.playbackRate = speed;
            setState("ready");
          }}
          onWaiting={() => setState((currentState) => (currentState === "error" ? currentState : "buffering"))}
          onPlaying={() => setState("playing")}
          onPause={() => setState((currentState) => (currentState === "ended" || currentState === "error" ? currentState : "paused"))}
          onEnded={() => setState("ended")}
          onTimeUpdate={() => rememberTime(false)}
          onSeeked={() => rememberTime(true)}
          onError={() => setState("error")}
        />
      </div>
      <div className="frame-controls">
        <button type="button" onClick={() => void play()} disabled={state === "error" || state === "playing"}>
          Play
        </button>
        <button type="button" onClick={pause} disabled={state !== "playing" && state !== "buffering"}>
          Pause
        </button>
        <button type="button" onClick={replay} disabled={state === "error" || state === "loading"}>
          Replay
        </button>
        <label htmlFor="playback-speed">
          Playback speed
          <select
            id="playback-speed"
            value={String(speed)}
            onChange={(event) => chooseSpeed(Number(event.target.value))}
          >
            {SPEEDS.map((value) => (
              <option key={value} value={value}>
                {value}x
              </option>
            ))}
          </select>
        </label>
      </div>
      <label htmlFor="playback-position">
        Playback position, seconds
        <input
          id="playback-position"
          type="range"
          min={0}
          max={ready ? duration : 0}
          step={0.1}
          value={ready ? Math.min(current, duration) : 0}
          disabled={!ready}
          onChange={(event) => seek(Number(event.target.value))}
        />
      </label>
    </section>
  );
  },
);

function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60);
  const remain = whole % 60;
  return `${minutes}:${remain.toString().padStart(2, "0")}`;
}
