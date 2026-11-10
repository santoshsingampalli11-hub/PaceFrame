/** A starting region for review. Not an event frame and not a capture-clock measurement. */

export function approximateReviewFrame(
  seconds: number,
  encodedFps: number,
  frameCount: number,
): { index: number; label: string } | null {
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  if (!Number.isFinite(encodedFps) || encodedFps <= 0) return null;
  if (!Number.isInteger(frameCount) || frameCount < 1) return null;
  const last = frameCount - 1;
  const index = Math.min(Math.max(Math.round(seconds * encodedFps), 0), last);
  return {
    index,
    label: `APPROXIMATE starting frame ${index}. The container rate was used only to choose a review region. It is not a verified capture clock and not the event frame.`,
  };
}
