import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import type { SessionLabels, SessionResponse, StoredMeasurement } from "../api/types";
import { missingPrerequisites } from "../components/KneeMeasurementPanel";

const sessionId = "ab".repeat(16);

const session: SessionResponse = {
  session_id: sessionId,
  bowler_id: "B01",
  delivery_id: "D01",
  video_filename: "video.avi",
  video_sha256: "d".repeat(64),
  width: 32,
  height: 24,
  encoded_fps: 10,
  decoded_frame_count: 4,
  orientation: "landscape",
  status: "created",
  front_leg: "left",
  camera_side_on_confirmed: false,
  full_body_visibility_confirmed: false,
  scientific_caveat: "Decoding does not mean this video is suitable.",
};

function labels(overrides: Partial<SessionLabels> = {}): SessionLabels {
  return {
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
    scientific_caveat: "A filename sidecar is not a hash.",
    ...overrides,
  };
}

function angle(degrees: number | null, status = degrees === null ? "unavailable" : "available") {
  return {
    frame_index: degrees === null ? 1 : 1,
    angle_degrees: degrees,
    status,
    reason: degrees === null ? "No pose was detected." : "",
    review_status: degrees === null ? "unavailable" : "no_structural_warning",
    warnings: degrees === null ? [] : ["Point is inside the image."],
    evidence: [
      { role: "hip", name: "left_hip", available: degrees !== null, visibility: 0.9, presence: 0.9 },
      { role: "knee", name: "left_knee", available: degrees !== null, visibility: null, presence: null },
      { role: "ankle", name: "left_ankle", available: false, visibility: null, presence: null },
    ],
  };
}

function measurement(ffcDegrees: number | null, releaseDegrees: number | null): StoredMeasurement {
  return {
    bowler_id: "B01",
    delivery_id: "D01",
    front_leg: "left",
    ffc_frame: 1,
    release_frame: 3,
    ffc: angle(ffcDegrees),
    release: angle(releaseDegrees),
    warnings: ["Side-on camera view is unconfirmed."],
    limitations: ["These are 2D image-plane angles."],
    annotation_provenance: "human_confirmed_filename_sidecar",
    annotation_byte_identity_verified: false,
    video_sha256: "d".repeat(64),
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderKnee() {
  return render(
    <MemoryRouter initialEntries={[`/sessions/${sessionId}/knee`]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  URL.createObjectURL = vi.fn(() => "blob:report") as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn();
});

describe("knee measurement", () => {
  it("lists each missing prerequisite and does not start a job", () => {
    expect(missingPrerequisites(null)).toEqual(["Saved labels were not found."]);
    expect(missingPrerequisites(labels({ front_leg: "", confirm_front_leg: false, confirm_label_link: false }))).toEqual(
      expect.arrayContaining([
        "Anatomical front leg is not saved.",
        "Front-leg confirmation was not recorded.",
        "The video-label confirmation was not recorded.",
      ]),
    );
    expect(missingPrerequisites(labels({ ffc_frame: 3, release_frame: 1 }))).toContain(
      "FFC must be earlier than Release.",
    );
  });

  it("keeps Start measurement off until the user confirms the label link again", async () => {
    const posts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse(labels());
        if (path.endsWith("/measure") && init?.method === "POST") {
          posts.push(String(init.body));
          return jsonResponse({ status: "queued", job_id: "cd".repeat(16), message: "queued" }, 202);
        }
        if (path.endsWith("/measure")) {
          if (posts.length === 0) return jsonResponse({ detail: "No measurement job was found." }, 404);
          return jsonResponse({
            session_id: sessionId,
            job_id: "cd".repeat(16),
            status: "running",
            message: "Measurement is running.",
            scientific_caveat: "2D only.",
          });
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderKnee();
    const button = await screen.findByRole("button", { name: "Start measurement" });
    expect(button).toBeDisabled();
    expect(await screen.findByText("Saved FFC frame")).toBeInTheDocument();
    expect(await screen.findByText("Saved Release frame")).toBeInTheDocument();
    await user.click(screen.getByLabelText("I confirm again that these saved labels belong to this video"));
    expect(screen.getByRole("button", { name: "Start measurement" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Start measurement" }));
    expect(posts).toEqual(['{"confirm_label_link":true}']);
    expect(await screen.findByText(/Measurement is running/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Measurement in progress…" })).toBeDisabled();
  });

  it("shows a completed report, unavailable angles, evidence, and a JSON download", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse(labels());
        if (path.endsWith("/measure")) {
          return jsonResponse({
            session_id: sessionId,
            job_id: "cd".repeat(16),
            status: "completed",
            message: "Measurement completed.",
            scientific_caveat: "2D only.",
          });
        }
        if (path.endsWith("/report")) {
          return jsonResponse({
            session_id: sessionId,
            job_id: "cd".repeat(16),
            status: "completed",
            scientific_caveat: "2D only.",
            report: measurement(142.5, null),
          });
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    renderKnee();
    expect(await screen.findByText("142.50°")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText(/hip left_hip: present/)).toBeInTheDocument();
    expect(screen.getByText(/Side-on camera view is unconfirmed/)).toBeInTheDocument();
    expect(screen.queryByText("0°")).not.toBeInTheDocument();
    await userDownload();
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeEnabled();
  });

  it("downloads stored FFC and Release rows as CSV and leaves the JSON download unchanged", async () => {
    const stored = measurement(142.5, null);
    stored.ffc = { ...stored.ffc, frame_index: 87 };
    stored.release = { ...stored.release, frame_index: 124, angle_degrees: null, status: "unavailable" };
    stored.ffc_frame = 87;
    stored.release_frame = 124;
    const blobs: Blob[] = [];
    const names: string[] = [];
    URL.createObjectURL = vi.fn((blob: Blob) => {
      blobs.push(blob);
      return `blob:${blobs.length}`;
    }) as typeof URL.createObjectURL;
    const realCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tagName: string, options?: ElementCreationOptions) => {
      const element = realCreate(tagName, options);
      if (tagName.toLowerCase() === "a") {
        const anchor = element as HTMLAnchorElement;
        const click = anchor.click.bind(anchor);
        anchor.click = () => {
          names.push(anchor.download);
          click();
        };
      }
      return element;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse(labels());
        if (path.endsWith("/measure")) {
          return jsonResponse({
            session_id: sessionId,
            job_id: "cd".repeat(16),
            status: "completed",
            message: "Measurement completed.",
            scientific_caveat: "2D only.",
          });
        }
        if (path.endsWith("/report")) {
          return jsonResponse({
            session_id: sessionId,
            job_id: "cd".repeat(16),
            status: "completed",
            scientific_caveat: "2D only.",
            report: stored,
          });
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderKnee();
    await user.click(await screen.findByRole("button", { name: "Download CSV" }));
    await user.click(screen.getByRole("button", { name: "Download JSON" }));
    expect(names).toEqual([`${sessionId}-front-knee.csv`, "B01_D01_measurement.json"]);
    const csv = await readBlob(blobs[0]);
    const json = await readBlob(blobs[1]);
    expect(csv).toContain("142.5");
    expect(csv).toContain("FFC");
    expect(csv).toContain("Release");
    expect(csv).toContain(",87,");
    expect(csv).toContain(",124,");
    expect(csv).not.toContain(",0,");
    expect(csv).not.toContain("video.avi");
    expect(json).toBe(JSON.stringify(stored, null, 2));
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it("shows a failed measurement without inventing an angle", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse(labels());
        if (path.endsWith("/measure")) {
          return jsonResponse({
            session_id: sessionId,
            job_id: "cd".repeat(16),
            status: "failed",
            message: "The pose model could not be loaded.",
            scientific_caveat: "2D only.",
          });
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const view = renderKnee();
    expect(await screen.findByText(/pose model could not be loaded/)).toBeInTheDocument();
    expect(screen.queryByText(/°/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeDisabled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    view.unmount();
  });

  it("shows a capacity rejection and does not invent an angle", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse(labels());
        if (path.endsWith("/measure") && init?.method === "POST") {
          return jsonResponse({ detail: "Measurement capacity is full." }, 503);
        }
        if (path.endsWith("/measure")) return jsonResponse({ detail: "No measurement job was found." }, 404);
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderKnee();
    const confirm = await screen.findByRole("checkbox", { name: /confirm again/i });
    await user.click(confirm);
    const start = await screen.findByRole("button", { name: "Start measurement" });
    expect(start).toBeEnabled();
    await user.click(start);
    expect(await screen.findByRole("alert")).toHaveTextContent("capacity is full");
    expect(screen.queryByText(/°/)).not.toBeInTheDocument();
  });

  it("shows a missing-label state without a measurement request", async () => {
    const posts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse({ detail: "No labels were found." }, 404);
        if (init?.method === "POST") posts.push("post");
        return jsonResponse({ detail: "No measurement job was found." }, 404);
      }),
    );
    renderKnee();
    expect(await screen.findByText("Saved labels were not found.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Event Annotation" })).toHaveAttribute(
      "href",
      `/sessions/${sessionId}/events`,
    );
    expect(screen.getByRole("button", { name: "Start measurement" })).toBeDisabled();
    expect(posts).toHaveLength(0);
  });

  it("keeps the knee page visible when the server is unreachable or the report is malformed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) throw new TypeError("Failed to fetch");
        return jsonResponse({ status: "completed" });
      }),
    );
    renderKnee();
    expect(await screen.findByRole("heading", { name: "Knee Kinematics" })).toBeInTheDocument();
    expect(await screen.findByText(/not reachable/)).toBeInTheDocument();
    expect(screen.queryByText("0°")).not.toBeInTheDocument();
  });
});

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

async function userDownload() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Download JSON" }));
}
