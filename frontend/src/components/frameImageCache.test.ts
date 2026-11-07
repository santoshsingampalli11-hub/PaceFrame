import { beforeEach, describe, expect, it } from "vitest";
import { cachedFrameUrl, resetOriginalFrameCache, storeFrameUrl } from "./frameImageCache";

const sessionA = "ab".repeat(16);
const sessionB = "cd".repeat(16);

function blob(byte: number): Blob {
  return new Blob([new Uint8Array([byte])]);
}

beforeEach(() => {
  resetOriginalFrameCache();
});

describe("original frame image cache", () => {
  it("keeps each session and index separate and does not create a new URL on a hit", () => {
    let calls = 0;
    URL.createObjectURL = (() => {
      calls += 1;
      return `blob:frame-${calls}`;
    }) as typeof URL.createObjectURL;
    const first = storeFrameUrl(sessionA, 4, blob(1));
    const other = storeFrameUrl(sessionB, 4, blob(2));
    expect(calls).toBe(2);
    expect(cachedFrameUrl(sessionA, 4)).toBe(first);
    expect(cachedFrameUrl(sessionB, 4)).toBe(other);
    expect(first).not.toBe(other);
    expect(calls).toBe(2);
  });

  it("drops the oldest stored frame and does not invent an index", () => {
    const urls = Array.from({ length: 8 }, (_, index) => storeFrameUrl(sessionA, index, blob(index + 1)));
    storeFrameUrl(sessionA, 8, blob(9));
    expect(cachedFrameUrl(sessionA, 0)).toBeUndefined();
    expect(cachedFrameUrl(sessionA, 1)).toBe(urls[1]);
    expect(cachedFrameUrl(sessionA, 8)).toBeTruthy();
    expect(cachedFrameUrl(sessionA, 99)).toBeUndefined();
  });
});
