import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { API_BASE_URL } from "../api/client";
import { OriginalVideoPlayer } from "../components/OriginalVideoPlayer";
import type { SessionResponse } from "../api/types";

const sessionId = "cd".repeat(16);
const otherId = "ab".repeat(16);

const session: SessionResponse = {
  session_id: sessionId,
  bowler_id: "B01",
  delivery_id: "D01",
  video_filename: "video.mp4",
  video_sha256: "b".repeat(64),
  width: 32,
  height: 24,
  encoded_fps: 10,
  decoded_frame_count: 4,
  orientation: "landscape",
  status: "created",
  front_leg: null,
  camera_side_on_confirmed: false,
  full_body_visibility_confirmed: false,
  scientific_caveat: "Decoding does not mean this video is suitable.",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve()) as typeof HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.pause = vi.fn();
});

describe("original video player", () => {
  it("points the video element at the session stream and does not autoplay", () => {
    render(<OriginalVideoPlayer sessionId={sessionId} frameWidth={32} frameHeight={24} />);
    const video = screen.getByLabelText("Original uploaded video") as HTMLVideoElement;
    expect(video).toHaveAttribute("src", `${API_BASE_URL}/api/sessions/${sessionId}/video`);
    expect(video).toHaveAttribute("preload", "metadata");
    expect(video.autoplay).toBe(false);
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(screen.getByText("Loading video information…")).toBeInTheDocument();
  });

  it("plays, pauses, changes speed, seeks, and replays without writing labels", async () => {
    const user = userEvent.setup();
    const posts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === "POST" || init?.method === "PUT") posts.push(String(init.body));
        return jsonResponse({ detail: "not used" }, 404);
      }),
    );
    render(<OriginalVideoPlayer sessionId={sessionId} />);
    const video = screen.getByLabelText("Original uploaded video") as HTMLVideoElement;
    Object.defineProperty(video, "duration", { configurable: true, value: 12 });
    Object.defineProperty(video, "currentTime", { configurable: true, writable: true, value: 0 });
    video.dispatchEvent(new Event("loadedmetadata"));
    expect(await screen.findByText(/Ready/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Play" }));
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    fireEvent.playing(video);
    expect(await screen.findByText(/Playing/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Pause" }));
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText("Playback speed"), "0.25");
    expect(video.playbackRate).toBe(0.25);
    await user.selectOptions(screen.getByLabelText("Playback speed"), "0.5");
    expect(video.playbackRate).toBe(0.5);

    const position = screen.getByLabelText("Playback position, seconds");
    await user.click(position);
    video.dispatchEvent(new Event("seeked"));
    await user.click(screen.getByRole("button", { name: "Replay" }));
    expect(video.currentTime).toBe(0);
    expect(posts).toEqual([]);
  });

  it("shows a codec fallback and leaves the upload unmarked", async () => {
    render(<OriginalVideoPlayer sessionId={sessionId} />);
    fireEvent.error(screen.getByLabelText("Original uploaded video"));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not play the original file");
    expect(screen.getByRole("alert")).toHaveTextContent("upload was not modified");
    expect(screen.getByRole("button", { name: "Play" })).toBeDisabled();
  });

  it("pauses when the player unmounts and changes source with the session", () => {
    const view = render(<OriginalVideoPlayer sessionId={sessionId} />);
    const video = screen.getByLabelText("Original uploaded video") as HTMLVideoElement;
    view.rerender(<OriginalVideoPlayer sessionId={otherId} />);
    expect(video).toHaveAttribute("src", `${API_BASE_URL}/api/sessions/${otherId}/video`);
    view.unmount();
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it("waits for the seek to finish before replaying after the video ends", async () => {
    const user = userEvent.setup();
    render(<OriginalVideoPlayer sessionId={sessionId} />);
    const video = screen.getByLabelText("Original uploaded video") as HTMLVideoElement;
    const seek = holdSeek(video, 4);
    fireEvent.loadedMetadata(video);
    fireEvent.ended(video);
    expect(await screen.findByText(/Ended/)).toBeInTheDocument();
    const play = vi.mocked(HTMLMediaElement.prototype.play);
    play.mockClear();
    await user.click(screen.getByRole("button", { name: "Replay" }));
    expect(play).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Replay" })).toBeDisabled();
    seek.complete();
    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));
    fireEvent.playing(video);
    expect(await screen.findByText(/Playing/)).toBeInTheDocument();
  });

  it("ignores another Replay click while the first seek is pending", async () => {
    const user = userEvent.setup();
    render(<OriginalVideoPlayer sessionId={sessionId} />);
    const video = screen.getByLabelText("Original uploaded video") as HTMLVideoElement;
    const seek = holdSeek(video, 4);
    fireEvent.loadedMetadata(video);
    const play = vi.mocked(HTMLMediaElement.prototype.play);
    play.mockClear();
    await user.click(screen.getByRole("button", { name: "Replay" }));
    expect(screen.getByRole("button", { name: "Replay" })).toBeDisabled();
    seek.complete();
    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "Replay" }));
    seek.complete();
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
  });

  it("does not start playback when the seek fails", async () => {
    const user = userEvent.setup();
    render(<OriginalVideoPlayer sessionId={sessionId} />);
    const video = screen.getByLabelText("Original uploaded video") as HTMLVideoElement;
    Object.defineProperty(video, "duration", { configurable: true, value: 4 });
    Object.defineProperty(video, "ended", { configurable: true, get: () => true });
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      get: () => 4,
      set: () => {
        throw new Error("seek failed");
      },
    });
    fireEvent.loadedMetadata(video);
    const play = vi.mocked(HTMLMediaElement.prototype.play);
    play.mockClear();
    await user.click(screen.getByRole("button", { name: "Replay" }));
    expect(await screen.findByText("Playback did not start. Press Play again when the video is ready.")).toBeInTheDocument();
    expect(play).not.toHaveBeenCalled();
  });

  it("does not play when the player unmounts during the seek", async () => {
    const user = userEvent.setup();
    const view = render(<OriginalVideoPlayer sessionId={sessionId} />);
    const video = screen.getByLabelText("Original uploaded video") as HTMLVideoElement;
    const seek = holdSeek(video, 4);
    fireEvent.loadedMetadata(video);
    const play = vi.mocked(HTMLMediaElement.prototype.play);
    play.mockClear();
    await user.click(screen.getByRole("button", { name: "Replay" }));
    view.unmount();
    seek.complete();
    await Promise.resolve();
    expect(play).not.toHaveBeenCalled();
  });

  it("keeps the playing state when metadata arrives again", async () => {
    render(<OriginalVideoPlayer sessionId={sessionId} />);
    const video = screen.getByLabelText("Original uploaded video") as HTMLVideoElement;
    Object.defineProperty(video, "duration", { configurable: true, value: 4 });
    fireEvent.loadedMetadata(video);
    fireEvent.playing(video);
    expect(await screen.findByText(/Playing/)).toBeInTheDocument();
    fireEvent.loadedMetadata(video);
    expect(screen.getByText(/Playing/)).toBeInTheDocument();
    expect(video.playbackRate).toBe(1);
  });

  it("reports a rejected play after the seek has settled", async () => {
    const user = userEvent.setup();
    HTMLMediaElement.prototype.play = vi.fn(() => Promise.reject(new Error("blocked"))) as typeof HTMLMediaElement.prototype.play;
    render(<OriginalVideoPlayer sessionId={sessionId} />);
    const video = screen.getByLabelText("Original uploaded video") as HTMLVideoElement;
    Object.defineProperty(video, "duration", { configurable: true, value: 4 });
    Object.defineProperty(video, "currentTime", { configurable: true, writable: true, value: 4 });
    Object.defineProperty(video, "ended", { configurable: true, get: () => false });
    fireEvent.loadedMetadata(video);
    await user.click(screen.getByRole("button", { name: "Replay" }));
    expect(await screen.findByText("Playback did not start. Press Play again when the video is ready.")).toBeInTheDocument();
  });
});

function holdSeek(video: HTMLVideoElement, duration: number) {
  let time = duration;
  let seeking = false;
  Object.defineProperty(video, "duration", { configurable: true, value: duration });
  Object.defineProperty(video, "currentTime", {
    configurable: true,
    get: () => time,
    set: (value: number) => {
      seeking = true;
      time = value;
    },
  });
  Object.defineProperty(video, "seeking", { configurable: true, get: () => seeking });
  Object.defineProperty(video, "ended", { configurable: true, get: () => time >= duration && time !== 0 });
  return {
    complete() {
      seeking = false;
      time = 0;
      fireEvent.seeked(video);
    },
  };
}

describe("review page playback", () => {
  it("keeps exact-frame review and pose review beside playback", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        if (init?.method === "POST" || init?.method === "PUT") {
          throw new Error("playback must not write labels");
        }
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.includes("/video/frames/")) {
          return new Response(new Uint8Array([1, 2, 3, 4]), {
            status: 200,
            headers: { "content-type": "image/jpeg" },
          });
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    render(
      <MemoryRouter initialEntries={[`/sessions/${sessionId}/review`]}>
        <AppRoutes />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "Video playback" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Exact frame review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pose review" })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: "Original decoded frame 0" })).toBeInTheDocument();
    expect(screen.getByLabelText("Original uploaded video")).toHaveAttribute(
      "src",
      `${API_BASE_URL}/api/sessions/${sessionId}/video`,
    );
  });
});
