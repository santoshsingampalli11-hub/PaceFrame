import { describe, expect, it } from "vitest";
import { approximateReviewFrame } from "./approximateFrame";

describe("approximate review frame", () => {
  it("uses the container rate only as a clamped starting index", () => {
    const region = approximateReviewFrame(1.24, 10, 20);
    expect(region?.index).toBe(12);
    expect(region?.label).toMatch(/^APPROXIMATE starting frame 12/);
    expect(region?.label).toMatch(/not a verified capture clock/);
    expect(region?.label).toMatch(/not the event frame/);
  });

  it("does not guess when the container rate or time is unusable", () => {
    expect(approximateReviewFrame(1, 0, 10)).toBeNull();
    expect(approximateReviewFrame(1, Number.NaN, 10)).toBeNull();
    expect(approximateReviewFrame(-1, 30, 10)).toBeNull();
    expect(approximateReviewFrame(3, 30, 0)).toBeNull();
  });

  it("stays inside the decoded range", () => {
    expect(approximateReviewFrame(100, 30, 8)?.index).toBe(7);
    expect(approximateReviewFrame(0, 30, 8)?.index).toBe(0);
  });
});
