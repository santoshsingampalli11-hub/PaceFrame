import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import type { SessionLabels, SessionResponse } from "../api/types";
import { validateEventDraft } from "../components/ManualEventAnnotationPanel";
import { resetOriginalFrameCache } from "../components/frameImageCache";

const sessionId = "ef".repeat(16);

const session: SessionResponse = {
  session_id: sessionId,
  bowler_id: "B01",
  delivery_id: "D01",
  video_filename: "video.avi",
  video_sha256: "c".repeat(64),
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

const savedLabels: SessionLabels = {
  session_id: sessionId,
  bowler_id: "B01",
  delivery_id: "D01",
  video_filename: "video.avi",
  bfc_frame: null,
  ffc_frame: 1,
  release_frame: 3,
  labeler: "SS",
  notes: "",
  front_leg: "left",
  confirm_front_leg: true,
  confirm_label_link: true,
  annotation_provenance: "human_confirmed_filename_sidecar",
  annotation_byte_identity_verified: false,
  scientific_caveat: "A matching filename sidecar is not a SHA-256.",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function jpeg(): Response {
  return new Response(new Uint8Array([9, 9, 9, 9]), {
    status: 200,
    headers: { "content-type": "image/jpeg" },
  });
}

function renderSession() {
  return render(
    <MemoryRouter initialEntries={[`/sessions/${sessionId}/events`]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  resetOriginalFrameCache();
  URL.createObjectURL = vi.fn(() => "blob:event") as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn();
});

describe("manual event annotation", () => {
  it("rejects bad order and out-of-range drafts without reordering them", () => {
    expect(
      validateEventDraft({ bfc: null, ffc: 3, release: 1 }, 4, "left", true, true, "SS"),
    ).toMatch(/FFC must be earlier than Release/);
    expect(
      validateEventDraft({ bfc: 2, ffc: 1, release: 3 }, 4, "left", true, true, "SS"),
    ).toMatch(/BFC must be earlier than FFC/);
    expect(validateEventDraft({ bfc: null, ffc: 1, release: 3 }, 4, "left", true, true, "SS")).toBeNull();
    expect(
      validateEventDraft({ bfc: null, ffc: 8, release: 9 }, 4, "left", true, true, "SS"),
    ).toMatch(/outside the decoded video/);
  });

  it("does not mark a frame until its image is displayed", async () => {
    const pendingFrames: Array<(value: Response) => void> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse({ detail: "No labels were found." }, 404);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.includes("/video/frames/")) {
          return new Promise<Response>((resolve) => {
            pendingFrames.push(resolve);
          });
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    const mark = await screen.findByRole("button", { name: "Mark FFC" });
    expect(mark).toBeDisabled();
    expect(screen.getByText("not loaded")).toBeInTheDocument();
    await waitFor(() => {
      pendingFrames.forEach((resolve) => resolve(jpeg()));
      expect(screen.getByRole("img", { name: "Original decoded frame 0" })).toBeInTheDocument();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Mark FFC" })).toBeEnabled());
  });

  it("keeps the shown frame and disables marking while the next frame loads", async () => {
    let releaseNext: (value: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse({ detail: "No labels were found." }, 404);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.endsWith("/frames/1")) {
          return new Promise<Response>((resolve) => {
            releaseNext = resolve;
          });
        }
        if (path.includes("/video/frames/")) return jpeg();
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    expect(await screen.findByRole("img", { name: "Original decoded frame 0" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Mark FFC" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    expect(screen.getByRole("img", { name: "Original decoded frame 0" })).toBeInTheDocument();
    expect(screen.getByText("not loaded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark BFC" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Mark FFC" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Mark Release" })).toBeDisabled();
    releaseNext(jpeg());
    expect(await screen.findByRole("img", { name: "Original decoded frame 1" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Mark FFC" })).toBeEnabled());
  });

  it("saves BFC, FFC and Release from the displayed frames", async () => {
    const puts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`) && !init?.method) return jsonResponse(session);
        if (path.endsWith("/labels") && init?.method === "PUT") {
          puts.push(String(init.body));
          return jsonResponse({ ...savedLabels, bfc_frame: 0, ffc_frame: 1, release_frame: 2 });
        }
        if (path.endsWith("/labels")) return jsonResponse({ detail: "No labels were found." }, 404);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.includes("/video/frames/")) return jpeg();
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    await screen.findByRole("img", { name: "Original decoded frame 0" });
    await user.click(screen.getByRole("button", { name: "Mark BFC" }));
    expect(screen.getByText(/Unsaved BFC: 0/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear BFC" }));
    expect(screen.getByText(/Unsaved BFC: not marked/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Mark BFC" }));
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    await screen.findByRole("img", { name: "Original decoded frame 1" });
    await user.click(screen.getByRole("button", { name: "Mark FFC" }));
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    await screen.findByRole("img", { name: "Original decoded frame 2" });
    await user.click(screen.getByRole("button", { name: "Mark Release" }));
    await user.selectOptions(screen.getByLabelText("Anatomical front leg"), "left");
    await user.click(screen.getByLabelText("I confirm this front leg"));
    await user.click(screen.getByLabelText("I confirm these labels belong to this video"));
    await user.type(screen.getByLabelText("Labeler id"), "SS");
    await user.click(screen.getByRole("button", { name: "Save labels" }));
    expect(await screen.findByText("Labels saved.")).toBeInTheDocument();
    expect(JSON.parse(puts[0])).toEqual({
      bfc_frame: 0,
      ffc_frame: 1,
      release_frame: 2,
      front_leg: "left",
      confirm_front_leg: true,
      confirm_label_link: true,
      labeler: "SS",
      notes: "",
      replace_existing: false,
    });
  });

  it("shows saved labels and does not replace them", async () => {
    const puts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels") && init?.method === "PUT") {
          puts.push("put");
          return jsonResponse({ detail: "Labels already exist for this session." }, 409);
        }
        if (path.endsWith("/labels")) return jsonResponse(savedLabels);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.includes("/video/frames/")) return jpeg();
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    expect(await screen.findByText("Labels are already saved for this session. Replacing them is not available here.")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save labels" })).not.toBeInTheDocument();
    expect(puts).toHaveLength(0);
  });

  it("does not treat a corrupt label response as verified", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse({ ffc_frame: "none", release_frame: false });
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.includes("/video/frames/")) return jpeg();
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    expect(await screen.findByRole("heading", { name: "Event Annotation" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("unexpected response");
    expect(screen.queryByText("Labels are already saved")).not.toBeInTheDocument();
  });

  it("keeps the unsaved selection when saving fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`) && !init?.method) return jsonResponse(session);
        if (path.endsWith("/labels") && init?.method === "PUT") {
          return jsonResponse({ detail: "The labels could not be saved." }, 500);
        }
        if (path.endsWith("/labels")) return jsonResponse({ detail: "No labels were found." }, 404);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "No pose review job was found." }, 404);
        if (path.includes("/video/frames/")) return jpeg();
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderSession();
    await screen.findByRole("img", { name: "Original decoded frame 0" });
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    await screen.findByRole("img", { name: "Original decoded frame 1" });
    await user.click(screen.getByRole("button", { name: "Mark FFC" }));
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    await screen.findByRole("img", { name: "Original decoded frame 2" });
    await user.click(screen.getByRole("button", { name: "Mark Release" }));
    await user.selectOptions(screen.getByLabelText("Anatomical front leg"), "right");
    await user.click(screen.getByLabelText("I confirm this front leg"));
    await user.click(screen.getByLabelText("I confirm these labels belong to this video"));
    await user.type(screen.getByLabelText("Labeler id"), "SS");
    await user.click(screen.getByRole("button", { name: "Save labels" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be saved");
    expect(screen.getByText(/Unsaved FFC: 1/)).toBeInTheDocument();
    expect(screen.queryByText("Labels saved.")).not.toBeInTheDocument();
  });

  it("shows a safe message when labels cannot be loaded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels") || path.endsWith("/pose-review")) throw new TypeError("Failed to fetch");
        if (path.includes("/video/frames/")) return jpeg();
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderSession();
    expect(await screen.findByRole("heading", { name: "Event Annotation" })).toBeInTheDocument();
    expect((await screen.findAllByText(/not reachable/)).length).toBeGreaterThan(0);
  });
});
