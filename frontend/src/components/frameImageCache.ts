/** Small in-memory map from a session and exact frame index to an object URL. */

const MAX_FRAMES = 8;
const urls = new Map<string, string>();

function key(sessionId: string, index: number): string {
  return `${sessionId}:${index}`;
}

export function resetOriginalFrameCache(): void {
  for (const url of urls.values()) URL.revokeObjectURL(url);
  urls.clear();
}

export function cachedFrameUrl(sessionId: string, index: number): string | undefined {
  const id = key(sessionId, index);
  const url = urls.get(id);
  if (!url) return undefined;
  urls.delete(id);
  urls.set(id, url);
  return url;
}

export function storeFrameUrl(sessionId: string, index: number, blob: Blob): string {
  const id = key(sessionId, index);
  const existing = urls.get(id);
  if (existing) {
    urls.delete(id);
    urls.set(id, existing);
    return existing;
  }
  const url = URL.createObjectURL(blob);
  urls.set(id, url);
  while (urls.size > MAX_FRAMES) {
    const oldest = urls.keys().next().value;
    if (oldest === undefined) break;
    const oldUrl = urls.get(oldest);
    urls.delete(oldest);
    if (oldUrl) URL.revokeObjectURL(oldUrl);
  }
  return url;
}
