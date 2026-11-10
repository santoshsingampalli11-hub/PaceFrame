import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import type { SessionLabels, SessionResponse, StoredMeasurement } from "../api/types";

const sessionId = "cd".repeat(16);

const session: SessionResponse = {
  session_id: sessionId,
  bowler_id: "B01",
  delivery_id: "D01",
  video_filename: "video.mp4",
  video_sha256: "e".repeat(64),
  width: 32,
  height: 24,
  encoded_fps: 10,
  decoded_frame_count: 8,
  orientation: "landscape",
  status: "created",
  front_leg: "right",
  camera_side_on_confirmed: false,
  full_body_visibility_confirmed: false,
  scientific_caveat: "Decoding does not mean this video is suitable.",
};

const labels: SessionLabels = {
  session_id: sessionId,
  bowler_id: "B01",
  delivery_id: "D01",
  video_filename: "video.mp4",
  bfc_frame: null,
  ffc_frame: 5,
  release_frame: 7,
  labeler: "SS",
  notes: "",
  front_leg: "right",
  confirm_front_leg: true,
  confirm_label_link: true,
  annotation_provenance: "human_confirmed_filename_sidecar",
  annotation_byte_identity_verified: false,
  scientific_caveat: "A filename sidecar is not a hash.",
};

const stored: StoredMeasurement = {
  bowler_id: "B01",
  delivery_id: "D01",
  front_leg: "right",
  ffc_frame: 5,
  release_frame: 7,
  ffc: {
    frame_index: 5,
    angle_degrees: 91.25,
    status: "available",
    reason: "",
    review_status: "no_structural_warning",
    warnings: [],
    evidence: [],
  },
  release: {
    frame_index: 7,
    angle_degrees: null,
    status: "unavailable",
    reason: "The pose was missing.",
    review_status: "unavailable",
    warnings: ['Quote "here", and a comma'],
    evidence: [],
  },
  warnings: ["Full-body visibility is unconfirmed."],
  limitations: ["These are 2D image-plane angles."],
  annotation_provenance: "human_confirmed_filename_sidecar",
  annotation_byte_identity_verified: false,
  video_sha256: "e".repeat(64),
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderReport() {
  return render(
    <MemoryRouter initialEntries={[`/sessions/${sessionId}/report`]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  URL.createObjectURL = vi.fn(() => "blob:report") as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn();
});

describe("analysis report export", () => {
  it("downloads the stored report as CSV and JSON", async () => {
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
        if (path.endsWith("/labels")) return jsonResponse(labels);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "not started" }, 404);
        if (path.endsWith("/measure")) {
          return jsonResponse({
            session_id: sessionId,
            job_id: "ef".repeat(16),
            status: "completed",
            message: "Measurement completed.",
            scientific_caveat: "2D only.",
          });
        }
        if (path.endsWith("/report")) {
          return jsonResponse({
            session_id: sessionId,
            job_id: "ef".repeat(16),
            status: "completed",
            scientific_caveat: "2D only.",
            report: stored,
          });
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderReport();
    expect(await screen.findByText("91.25°")).toBeInTheDocument();
    const releaseTile = screen.getByRole("heading", { name: "Ball release" }).closest("article");
    expect(releaseTile).toHaveTextContent("Unavailable");
    expect(releaseTile).not.toHaveTextContent("0.00°");
    expect(screen.getByRole("heading", { name: "2D Front Knee Kinematics" })).toBeInTheDocument();
    const headings = screen.getAllByRole("heading").map((heading) => heading.textContent);
    expect(headings.indexOf("2D Front Knee Kinematics")).toBeLessThan(headings.indexOf("Session"));
    expect(headings.indexOf("Manual events")).toBeLessThan(headings.indexOf("Session"));
    expect(screen.getByText("not marked")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("Not verified")).toBeInTheDocument();
    expect(screen.getByText("human_confirmed_filename_sidecar")).toBeInTheDocument();
    expect(screen.getByText(sessionId)).toBeInTheDocument();
    expect(screen.getByText("video.mp4")).toBeInTheDocument();
    expect(screen.getByText("32 × 24")).toBeInTheDocument();
    expect(screen.getByText("Recording conditions")).toBeInTheDocument();
    expect(screen.getByText('Quote "here", and a comma')).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Download CSV" }));
    await user.click(screen.getByRole("button", { name: "Download JSON" }));
    expect(names).toEqual([`${sessionId}-front-knee.csv`, "B01_D01_measurement.json"]);
    const csv = await readBlob(blobs[0]);
    expect(csv).toContain("91.25");
    expect(csv).toContain("FFC");
    expect(csv).toContain("Release");
    expect(csv).toContain('"Full-body visibility is unconfirmed.; Quote ""here"", and a comma"');
    expect(csv).not.toContain(",0,");
    expect(csv).not.toContain("video.mp4");
    expect(await readBlob(blobs[1])).toBe(JSON.stringify(stored, null, 2));
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it("shows two-decimal knee angles from the stored report and keeps full CSV precision", async () => {
    const precise = {
      ...stored,
      ffc: { ...stored.ffc, angle_degrees: 168.126, status: "available" },
      release: { ...stored.release, angle_degrees: 177.754, status: "available", warnings: [] },
    };
    const blobs: Blob[] = [];
    URL.createObjectURL = vi.fn((blob: Blob) => {
      blobs.push(blob);
      return `blob:${blobs.length}`;
    }) as typeof URL.createObjectURL;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse(labels);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "not started" }, 404);
        if (path.endsWith("/measure")) {
          return jsonResponse({
            session_id: sessionId,
            job_id: "ef".repeat(16),
            status: "completed",
            message: "Measurement completed.",
            scientific_caveat: "2D only.",
          });
        }
        if (path.endsWith("/report")) {
          return jsonResponse({ session_id: sessionId, status: "completed", report: precise });
        }
        return jsonResponse({ detail: "missing" }, 404);
      }),
    );
    const user = userEvent.setup();
    renderReport();
    expect(await screen.findByText("168.13°")).toBeInTheDocument();
    expect(screen.getByText("177.75°")).toBeInTheDocument();
    expect(screen.queryByText("168.126°")).not.toBeInTheDocument();
    expect(screen.getAllByText("Status: available")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Download CSV" }));
    const csv = await readBlob(blobs[0]);
    expect(csv).toContain("168.126");
    expect(csv).toContain("177.754");
    expect(csv.split("\n")[0]).toContain("angle_degrees");
  });

  it("does not offer a download when no measurement report is stored", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.endsWith(`/api/sessions/${sessionId}`)) return jsonResponse(session);
        if (path.endsWith("/labels")) return jsonResponse({ detail: "No labels were found." }, 404);
        if (path.endsWith("/pose-review")) return jsonResponse({ detail: "not started" }, 404);
        return jsonResponse({ detail: "No measurement job was found." }, 404);
      }),
    );
    renderReport();
    expect(await screen.findByText("No measurement report is stored yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeDisabled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByText("0°")).not.toBeInTheDocument();
  });
});
