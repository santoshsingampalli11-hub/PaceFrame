import { describe, expect, it } from "vitest";
import type { StoredMeasurement } from "../api/types";
import { presentLimitations } from "./scientificLimitations";

function measurement(overrides: Partial<StoredMeasurement> = {}): StoredMeasurement {
  return {
    bowler_id: "B01",
    delivery_id: "D01",
    front_leg: "left",
    ffc_frame: 10,
    release_frame: 20,
    ffc: {
      frame_index: 10,
      angle_degrees: null,
      status: "unavailable",
      reason: "No pose was detected.",
      review_status: "unavailable",
      warnings: [
        "left_knee has no visibility score. A missing score is not landmark accuracy, and no cutoff was applied.",
        "left_ankle has no presence score. A missing score is not landmark accuracy, and no cutoff was applied.",
      ],
      evidence: [],
    },
    release: {
      frame_index: 20,
      angle_degrees: 142.5,
      status: "available",
      reason: "",
      review_status: "review_required",
      warnings: ["left_hip is outside normalized image bounds (x=1.2, y=0.1). It was not clamped and is not an in-frame observation."],
      evidence: [],
    },
    warnings: [
      "Side-on camera view is unconfirmed. That is not scientific approval.",
      "Full-body visibility is unconfirmed. That is not scientific approval.",
      "Label linkage was confirmed by the caller for a matching filename. The sidecar does not store a video hash.",
    ],
    limitations: [
      "These are 2D image-plane angles from raw MediaPipe landmarks, not 3D joint angles.",
      "These are 2D image-plane angles from raw MediaPipe landmarks, not 3D joint angles.",
      "Unconfirmed side-on view and full-body visibility are not scientific approval.",
      "The label sidecar stores a filename, not a hash. Human confirmation of that filename is not byte-level proof.",
      "Visibility is not landmark accuracy. A missing pose is reported as unavailable, not as zero degrees.",
      "No manual reference angle and no accuracy statistic is included.",
    ],
    annotation_provenance: "human_confirmed_filename_sidecar",
    annotation_byte_identity_verified: false,
    video_sha256: "ab",
    ...overrides,
  };
}

describe("scientific limitation grouping", () => {
  it("consolidates repeated warnings into four categories and keeps an unknown warning", () => {
    const stored = measurement();
    stored.warnings.push("Pose tracking jumped to a second person.");
    const view = presentLimitations(stored);
    expect(view.groups.map((group) => group.id)).toEqual(["dimensionality", "recording", "provenance", "validation"]);
    expect(view.groups[0].text).toMatch(/2D image-plane/);
    expect(view.groups[0].text).toMatch(/not 3D/);
    expect(view.groups[1].text).toMatch(/Side-on camera view and full-body visibility are unconfirmed/);
    expect(view.groups[1].text).not.toMatch(/confirmed by a reviewer/);
    expect(view.groups[2].text).toMatch(/not byte-level proof/);
    expect(view.groups[3].text).toMatch(/not zero degrees/);
    expect(view.additional).toEqual([
      "Pose tracking jumped to a second person.",
      "left_hip is outside normalized image bounds (x=1.2, y=0.1). It was not clamped and is not an in-frame observation.",
    ]);
    expect(JSON.stringify(stored.warnings)).toContain("Side-on camera view is unconfirmed.");
    expect(JSON.stringify(stored.limitations)).toContain("not 3D joint angles");
  });

  it("does not say full-body visibility is unconfirmed when that warning is absent", () => {
    const stored = measurement({
      warnings: ["Side-on camera view is unconfirmed. That is not scientific approval."],
      limitations: [],
      ffc: { ...measurement().ffc, warnings: [], angle_degrees: null, status: "unavailable" },
      release: { ...measurement().release, warnings: [], angle_degrees: null, status: "unavailable" },
    });
    const view = presentLimitations(stored);
    expect(view.groups.map((group) => group.id)).toEqual(["recording"]);
    expect(view.groups[0].text).toBe("Side-on camera view is unconfirmed. That is not scientific approval.");
    expect(view.groups[0].text).not.toMatch(/full-body/);
  });
});
