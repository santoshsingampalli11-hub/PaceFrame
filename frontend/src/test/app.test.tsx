import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import type { SessionResponse } from "../api/types";

const session: SessionResponse = {
  session_id: "ab".repeat(16),
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

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("upload form", () => {
  it("shows field errors and does not upload an empty form after clearing ids", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/health")) return jsonResponse({ status: "healthy" });
        throw new Error("unexpected request");
      }),
    );
    const user = userEvent.setup();
    renderAt("/");
    await user.clear(screen.getByLabelText("Bowler id"));
    await user.clear(screen.getByLabelText("Delivery id"));
    await user.click(screen.getByRole("button", { name: "Upload and create session" }));
    expect(await screen.findByText("Choose a video file before uploading.")).toBeInTheDocument();
    expect(screen.getByText("Use an anonymous id such as B01.")).toBeInTheDocument();
    expect(screen.getByText("Use an anonymous id such as D01.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("posts multipart fields and opens the created session", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url: String(url), init });
        if (String(url).endsWith("/health")) return jsonResponse({ status: "healthy" });
        if (String(url).endsWith("/api/sessions") && init?.method === "POST") return jsonResponse(session);
        if (String(url).endsWith(`/api/sessions/${session.session_id}`)) return jsonResponse(session);
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderAt("/");
    const file = new File(["clip"], "delivery.avi", { type: "video/x-msvideo" });
    await user.upload(screen.getByLabelText("Video file"), file);
    expect(screen.getByText(/Selected locally: delivery.avi/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Anatomical front leg"), "left");
    await user.click(screen.getByRole("button", { name: "Upload and create session" }));

    await screen.findByRole("heading", { name: "Session details" });
    const upload = calls.find((call) => call.init?.method === "POST");
    const body = upload?.init?.body;
    expect(body).toBeInstanceOf(FormData);
    const form = body as FormData;
    expect(form.get("bowler_id")).toBe("B01");
    expect(form.get("delivery_id")).toBe("D01");
    expect(form.get("front_leg")).toBe("left");
    expect(form.get("video")).toBeInstanceOf(File);
    expect(screen.getByText("B01")).toBeInTheDocument();
    expect(screen.getByText("video.avi")).toBeInTheDocument();
    expect(screen.getByText("32 × 24")).toBeInTheDocument();
    expect(screen.getByText("Pose review, annotation, and measurement are separate steps")).toBeInTheDocument();
    expect(screen.queryByText(/analysed/i)).not.toBeInTheDocument();
    expect(screen.getByText(session.scientific_caveat)).toBeInTheDocument();
  });

  it("does not send a second upload while the first is in progress", async () => {
    let release: (value: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/health")) return jsonResponse({ status: "healthy" });
        if (init?.method === "POST") return pending;
        return jsonResponse(session);
      }),
    );
    const user = userEvent.setup();
    renderAt("/");
    await user.upload(
      screen.getByLabelText("Video file"),
      new File(["clip"], "delivery.mp4", { type: "video/mp4" }),
    );
    const form = screen.getByRole("button", { name: "Upload and create session" }).closest("form");
    expect(form).not.toBeNull();
    await act(async () => {
      form?.requestSubmit();
      form?.requestSubmit();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Uploading…" })).toBeDisabled());
    const posts = vi.mocked(fetch).mock.calls.filter((call) => call[1]?.method === "POST");
    expect(posts).toHaveLength(1);
    release(jsonResponse(session));
  });

  it("does not upload a file over 80 MiB", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/health")) return jsonResponse({ status: "healthy" });
        throw new Error("upload should not start");
      }),
    );
    const user = userEvent.setup();
    renderAt("/");
    const huge = new File([new Uint8Array(1)], "huge.mp4", { type: "video/mp4" });
    Object.defineProperty(huge, "size", { value: 80 * 1024 * 1024 + 1 });
    await user.upload(screen.getByLabelText("Video file"), huge);
    await user.click(screen.getByRole("button", { name: "Upload and create session" }));
    expect(await screen.findByText(/larger than the server limit of 80 MiB/)).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some((call) => call[1]?.method === "POST")).toBe(false);
  });

  it("shows a server rejection without a stack trace", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/health")) return jsonResponse({ status: "healthy" });
        if (init?.method === "POST") {
          return jsonResponse({ detail: "Unsupported video format." }, 415);
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderAt("/");
    await user.upload(
      screen.getByLabelText("Video file"),
      new File(["clip"], "clip.avi", { type: "video/x-msvideo" }),
    );
    await user.click(screen.getByRole("button", { name: "Upload and create session" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unsupported video format.");
    expect(screen.queryByText(/Traceback|C:\\/)).not.toBeInTheDocument();
  });

  it("reports when the backend cannot be reached", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    renderAt("/");
    expect(await screen.findByText("The analysis server is not reachable.")).toBeInTheDocument();
  });
});

describe("session page", () => {
  it("rejects an invalid session id without inventing a result", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderAt("/sessions/not-a-session");
    expect(await screen.findByRole("alert")).toHaveTextContent("This session id is not valid.");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/health");
    expect(screen.queryByText("Session details")).not.toBeInTheDocument();
  });
});
