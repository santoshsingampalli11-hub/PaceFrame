import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { resetOriginalFrameCache } from "../components/frameImageCache";
import type { PoseReviewReport, PoseReviewStatus, SessionResponse } from "../api/types";

const sessionId = "ab".repeat(16);

const session: SessionResponse = {
  session_id: sessionId,
  bowler_id: "B01",
  delivery_id: "D01",
  video_filename: "video.avi",
  video_sha256: "a".repeat(64),
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

function statusBody(status: PoseReviewStatus["status"], message: string): PoseReviewStatus {
  return {
    session_id: sessionId,
    job_id: "cd".repeat(16),
    status,
    message,
    created_at: "2026-11-05T00:00:00Z",
    started_at: null,
    finished_at: null,
    review_frames: [0, 2],
    scientific_caveat: "Detection is not a biomechanical measurement.",
  };
}

const report: PoseReviewReport = {
  session_id: sessionId,
  job_id: "cd".repeat(16),
  status: "completed",
  report_text: "pose_frames: 3\nmissing_pose_count: 1\nlandmark_availability:\n- nose: frames_with_landmark=3\n",
  pose_frames: 3,
  decoded_frame_count: 4,
  missing_pose_count: 1,
  scientific_caveat: "Detection is not a biomechanical measurement.",
  limitations: ["A detected pose is not proof that the person is the bowler."],
  overlay_frames: [0, 2],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
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
});

describe("pose review panel", () => {
  it("keeps the session page visible when pose review has not started", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.includes("/video/frames/")) {
          return new Response(new Uint8Array([1, 2, 3, 4]), {
            status: 200,
            headers: { "content-type": "image/jpeg" },
          });
        }
        if (path.endsWith("/pose-review")) {
          return jsonResponse({ detail: "No pose review job was found." }, 404);
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    expect(await screen.findByRole("heading", { name: "Video & Pose Review" })).toBeInTheDocument();
    expect(await screen.findByText("Pose review not started.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not crash when a completed report omits overlay_frames", async () => {
    const { overlay_frames: _omitted, ...withoutFrames } = report;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review/report")) return jsonResponse(withoutFrames);
        if (path.endsWith("/pose-review")) return jsonResponse(statusBody("completed", "Pose review completed."));
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    expect(await screen.findByRole("heading", { name: "Video & Pose Review" })).toBeInTheDocument();
    expect(await screen.findByText("No overlay images were exported. List frame indexes before starting a review if you want images.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
  it("starts a job with the requested frames and does not start twice while running", async () => {
    const posts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`) && !init?.method) return jsonResponse(session);
        if (path.endsWith("/pose-review") && init?.method === "POST") {
          posts.push(String(init.body));
          return jsonResponse({ status: "queued", job_id: "cd".repeat(16), message: "queued" });
        }
        if (path.endsWith("/pose-review") && posts.length === 0) {
          return jsonResponse({ detail: "No pose review job was found." }, 404);
        }
        if (path.endsWith("/pose-review")) return jsonResponse(statusBody("running", "Pose review is running."));
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    await screen.findByRole("heading", { name: "Pose review" });
    await user.type(screen.getByLabelText("Overlay frame indexes"), "0, 2");
    await user.click(screen.getByRole("button", { name: "Start pose review" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(JSON.parse(posts[0])).toEqual({ review_frames: [0, 2] });
    expect(await screen.findByRole("button", { name: "Pose review in progress…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Pose review in progress…" }));
    expect(posts).toHaveLength(1);
  });

  it("renders a completed report and moves only between exported frames", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review/report")) return jsonResponse(report);
        if (path.endsWith("/pose-review")) return jsonResponse(statusBody("completed", "Pose review completed."));
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    expect(await screen.findByText("Frames with a detected pose")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText(/not an accuracy percentage/i)).toBeInTheDocument();
    expect(screen.queryByText(/analysed/i)).not.toBeInTheDocument();
    const image = await screen.findByRole("img", { name: /decoded frame 0/i });
    expect(image).toHaveAttribute("src", expect.stringContaining(`/pose-review/frames/0`));
    await user.click(screen.getByRole("button", { name: "Next exported frame" }));
    expect(screen.getByRole("img", { name: /decoded frame 2/i })).toHaveAttribute(
      "src",
      expect.stringContaining("/pose-review/frames/2"),
    );
    expect(screen.queryByRole("option", { name: "1" })).not.toBeInTheDocument();
  });

  it("shows a failed job without a report or image", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) {
          return jsonResponse(statusBody("failed", "The pose model could not be loaded."));
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    expect(await screen.findByText(/pose model could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Diagnostic report" })).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("reports a missing overlay image", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.includes("/video/frames/")) {
          return new Response(new Uint8Array([1, 2, 3, 4]), {
            status: 200,
            headers: { "content-type": "image/jpeg" },
          });
        }
        if (path.endsWith("/pose-review/report")) return jsonResponse(report);
        if (path.endsWith("/pose-review")) return jsonResponse(statusBody("completed", "done"));
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    const image = await screen.findByRole("img", { name: "Raw pose overlay for decoded frame 0" });
    act(() => {
      image.dispatchEvent(new Event("error"));
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("was not found");
    expect(screen.getByRole("heading", { name: "Video & Pose Review" })).toBeInTheDocument();
  });

  it("shows an empty overlay list without inventing images", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review/report")) return jsonResponse({ ...report, overlay_frames: [] });
        if (path.endsWith("/pose-review")) return jsonResponse(statusBody("completed", "Pose review completed."));
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    expect(await screen.findByRole("heading", { name: "Video & Pose Review" })).toBeInTheDocument();
    expect(await screen.findByText(/No overlay images were exported/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it.each(["queued", "running"] as const)("keeps the session visible while pose review is %s", async (state) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/pose-review")) return jsonResponse(statusBody(state, `Pose review is ${state}.`));
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    expect(await screen.findByRole("heading", { name: "Video & Pose Review" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Pose review in progress…" })).toBeDisabled();
    expect(screen.queryByRole("heading", { name: "Diagnostic report" })).not.toBeInTheDocument();
  });

  it("shows a safe error when the analysis server is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.includes("/video/frames/")) {
          return new Response(new Uint8Array([1, 2, 3, 4]), {
            status: 200,
            headers: { "content-type": "image/jpeg" },
          });
        }
        throw new TypeError("Failed to fetch");
      }),
    );
    renderSession();
    expect(await screen.findByRole("heading", { name: "Video & Pose Review" })).toBeInTheDocument();
    expect((await screen.findAllByText(/not reachable/)).length).toBeGreaterThan(0);
  });

  it("shows a safe error for a malformed pose-review status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.includes("/video/frames/")) {
          return new Response(new Uint8Array([1, 2, 3, 4]), {
            status: 200,
            headers: { "content-type": "image/jpeg" },
          });
        }
        if (path.endsWith("/pose-review")) return jsonResponse({ status: "completed" });
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    expect(await screen.findByRole("heading", { name: "Video & Pose Review" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("The server returned an unexpected response.");
    expect(screen.queryByRole("img", { name: /Raw pose overlay/ })).not.toBeInTheDocument();
  });
});
