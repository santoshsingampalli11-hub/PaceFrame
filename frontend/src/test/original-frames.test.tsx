import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { resetOriginalFrameCache } from "../components/frameImageCache";
import type { SessionResponse } from "../api/types";

const sessionId = "cd".repeat(16);

const session: SessionResponse = {
  session_id: sessionId,
  bowler_id: "B01",
  delivery_id: "D01",
  video_filename: "video.avi",
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

function jpeg(marker: number): Response {
  return new Response(new Uint8Array([marker, marker, marker, marker]), {
    status: 200,
    headers: { "content-type": "image/jpeg" },
  });
}

function renderSession() {
  return render(
    <MemoryRouter initialEntries={[`/sessions/${sessionId}/review`]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  resetOriginalFrameCache();
  URL.createObjectURL = vi.fn((blob: Blob) => `blob:${blob.size}`) as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn();
});

describe("original frame viewer", () => {
  it("shows frame 0, then the next and previous exact frames", async () => {
    const requested: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        const match = path.match(/frames\/(\d+)$/);
        if (match) {
          requested.push(match[1]);
          return jpeg(Number(match[1]) + 1);
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    expect(await screen.findByRole("img", { name: "Original decoded frame 0" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Video & Pose Review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pose review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous frame" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    expect(await screen.findByRole("img", { name: "Original decoded frame 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Previous frame" }));
    expect(await screen.findByRole("img", { name: "Original decoded frame 0" })).toBeInTheDocument();
    expect(requested).toEqual(["0", "1"]);
  });

  it("jumps and slides only to valid indexes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        const match = path.match(/frames\/(\d+)$/);
        if (match) return jpeg(Number(match[1]) + 3);
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    await screen.findByRole("img", { name: "Original decoded frame 0" });
    await user.clear(screen.getByLabelText("Jump to frame"));
    await user.type(screen.getByLabelText("Jump to frame"), "3");
    await user.click(screen.getByRole("button", { name: "Show frame" }));
    expect(await screen.findByRole("img", { name: "Original decoded frame 3" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next frame" })).toBeDisabled();
    await user.clear(screen.getByLabelText("Jump to frame"));
    await user.type(screen.getByLabelText("Jump to frame"), "9");
    await user.click(screen.getByRole("button", { name: "Show frame" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("past the last decoded frame");
    expect(screen.getByRole("img", { name: "Original decoded frame 3" })).toBeInTheDocument();
    await user.click(screen.getByLabelText("Frame slider, 0 to 3"));
    await user.keyboard("{ArrowLeft}");
  });

  it("uses arrow keys on the viewer and not while typing a jump", async () => {
    const requested: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        const match = path.match(/frames\/(\d+)$/);
        if (match) {
          requested.push(match[1]);
          return jpeg(8);
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    const viewer = await screen.findByRole("region", { name: "Original video frames" });
    viewer.focus();
    await user.keyboard("{ArrowRight}");
    expect(await screen.findByRole("img", { name: "Original decoded frame 1" })).toBeInTheDocument();
    await user.click(screen.getByLabelText("Jump to frame"));
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("img", { name: "Original decoded frame 1" })).toBeInTheDocument();
    expect(requested.filter((index) => index === "0").length).toBeGreaterThan(0);
  });

  it("ignores a stale frame response", async () => {
    let rejectStale: (error: unknown) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.endsWith("/frames/1")) {
          return new Promise((_resolve, reject) => {
            rejectStale = reject;
            init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
          });
        }
        if (path.endsWith("/frames/2")) return jpeg(2);
        if (path.endsWith("/frames/0")) return jpeg(4);
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    await screen.findByRole("img", { name: "Original decoded frame 0" });
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    expect(await screen.findByRole("img", { name: "Original decoded frame 2" })).toBeInTheDocument();
    rejectStale(new DOMException("Aborted", "AbortError"));
    expect(screen.getByRole("img", { name: "Original decoded frame 2" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Original decoded frame 1" })).not.toBeInTheDocument();
  });

  it("shows a retryable error and does not invent an image", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.includes("/video/frames/")) return jsonResponse({ detail: "That decoded frame is not available." }, 404);
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    expect(await screen.findByRole("heading", { name: "Video & Pose Review" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("That decoded frame is not available.");
    expect(screen.getByRole("button", { name: "Retry frame" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Original decoded frame/ })).not.toBeInTheDocument();
  });

  it("keeps the previous frame visible while the next frame loads", async () => {
    let releaseNext: (value: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.endsWith("/frames/0")) return jpeg(4);
        if (path.endsWith("/frames/1")) {
          return new Promise<Response>((resolve) => {
            releaseNext = resolve;
            init?.signal?.addEventListener("abort", () => resolve(jpeg(0)));
          });
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    expect(await screen.findByRole("img", { name: "Original decoded frame 0" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    expect(screen.getByRole("img", { name: "Original decoded frame 0" })).toBeInTheDocument();
    expect(screen.getByText("Showing frame 0 — loading frame 1")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Original decoded frame 1" })).not.toBeInTheDocument();
    releaseNext(jpeg(8));
    expect(await screen.findByRole("img", { name: "Original decoded frame 1" })).toBeInTheDocument();
    expect(screen.getByText("Showing frame 1")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Original decoded frame 0" })).not.toBeInTheDocument();
  });

  it("keeps the old frame when the next request fails and retries that index", async () => {
    let failNext = true;
    const requested: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        const match = path.match(/frames\/(\d+)$/);
        if (match) {
          requested.push(match[1]);
          if (match[1] === "1" && failNext) return jsonResponse({ detail: "That decoded frame is not available." }, 404);
          return jpeg(Number(match[1]) + 1);
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    await screen.findByRole("img", { name: "Original decoded frame 0" });
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Still showing frame 0");
    expect(screen.getByRole("img", { name: "Original decoded frame 0" })).toBeInTheDocument();
    failNext = false;
    await user.click(screen.getByRole("button", { name: "Retry frame" }));
    expect(await screen.findByRole("img", { name: "Original decoded frame 1" })).toBeInTheDocument();
    expect(requested.filter((index) => index === "1").length).toBe(2);
  });

  it("keeps the last frame and offers retry when the decoder is busy", async () => {
    let busy = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.endsWith("/frames/0")) return jpeg(4);
        if (path.endsWith("/frames/1") && busy) {
          return jsonResponse({ detail: "Frame decoding capacity is full." }, 503);
        }
        if (path.endsWith("/frames/1")) return jpeg(8);
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    await screen.findByRole("img", { name: "Original decoded frame 0" });
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The frame decoder is busy");
    expect(screen.getByRole("alert")).toHaveTextContent("not used for marking");
    expect(screen.getByRole("img", { name: "Original decoded frame 0" })).toBeInTheDocument();
    busy = false;
    await user.click(screen.getByRole("button", { name: "Retry frame" }));
    expect(await screen.findByRole("img", { name: "Original decoded frame 1" })).toBeInTheDocument();
  });
});
