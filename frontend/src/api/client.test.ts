import { describe, expect, it } from "vitest";

import { API_BASE_URL, originalVideoUrl, poseReviewFrameUrl } from "./client";

describe("production API routing", () => {
  it("uses same-origin paths when no API base URL is set", () => {
    expect(API_BASE_URL).toBe("");
    expect(API_BASE_URL).not.toContain("localhost");
    expect(API_BASE_URL).not.toContain("127.0.0.1");
    expect(originalVideoUrl("abc")).toBe("/api/sessions/abc/video");
    expect(poseReviewFrameUrl("abc", 30)).toBe("/api/sessions/abc/pose-review/frames/30");
  });
});
