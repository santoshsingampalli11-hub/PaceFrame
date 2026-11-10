import type { StoredMeasurement } from "../api/types";

export type LimitationCategoryId = "dimensionality" | "recording" | "provenance" | "validation";

export type LimitationGroup = {
  id: LimitationCategoryId;
  title: string;
  text: string;
};

export type LimitationPresentation = {
  groups: LimitationGroup[];
  additional: string[];
};

const TITLES: Record<LimitationCategoryId, string> = {
  dimensionality: "Measurement type and dimensionality",
  recording: "Recording conditions",
  provenance: "Manual event-label provenance",
  validation: "Measurement validation and limitations",
};

/** Known stored sentences. Anything else stays visible as an additional warning. */
function categoryFor(warning: string): LimitationCategoryId | null {
  const text = warning.toLowerCase();
  if (/2d image-plane|not 3d/.test(text)) return "dimensionality";
  if (/side-on|full-body visibility|does not confirm camera view/.test(text)) return "recording";
  if (/sidecar|filename, not a hash|byte-level proof|label linkage/.test(text)) return "provenance";
  if (
    /visibility is not landmark accuracy|missing score is not landmark accuracy|no cutoff was applied|not as zero|not zero degrees|no manual reference angle|no accuracy statistic/.test(
      text,
    )
  ) {
    return "validation";
  }
  return null;
}

export function presentLimitations(
  measurement: Pick<StoredMeasurement, "warnings" | "limitations" | "ffc" | "release"> | null | undefined,
): LimitationPresentation {
  const texts = uniqueStrings([
    ...(measurement?.warnings ?? []),
    ...(measurement?.limitations ?? []),
    ...(measurement?.ffc?.warnings ?? []),
    ...(measurement?.release?.warnings ?? []),
  ]);
  const grouped: Record<LimitationCategoryId, string[]> = {
    dimensionality: [],
    recording: [],
    provenance: [],
    validation: [],
  };
  const additional: string[] = [];
  for (const text of texts) {
    const category = categoryFor(text);
    if (category) grouped[category].push(text);
    else additional.push(text);
  }
  const groups = (Object.keys(grouped) as LimitationCategoryId[])
    .filter((id) => grouped[id].length > 0)
    .map((id) => ({ id, title: TITLES[id], text: explanation(id, grouped[id]) }));
  return { groups, additional };
}

function explanation(id: LimitationCategoryId, matched: string[]): string {
  if (id === "dimensionality") {
    return "These are 2D image-plane angles from raw pose landmarks. They are not 3D laboratory joint angles.";
  }
  if (id === "recording") return recordingText(matched);
  if (id === "provenance") {
    return "The labels are tied to this video by a human-confirmed filename. The sidecar does not store a video hash, so that confirmation is not byte-level proof.";
  }
  return validationText(matched);
}

function recordingText(matched: string[]): string {
  const blob = matched.join(" ").toLowerCase();
  const sideOn = /side-on/.test(blob) && /unconfirmed/.test(blob);
  const fullBody = /full-body visibility/.test(blob) && /unconfirmed|not scientific approval/.test(blob);
  const hashOnly = /does not confirm camera view/.test(blob);
  if (sideOn && fullBody) {
    return "Side-on camera view and full-body visibility are unconfirmed. That is not scientific approval. A file hash does not confirm the camera view.";
  }
  if (sideOn) return "Side-on camera view is unconfirmed. That is not scientific approval.";
  if (fullBody) return "Full-body visibility is unconfirmed. That is not scientific approval.";
  if (hashOnly) {
    return "A file hash means the stored bytes match the manifest. It does not confirm camera view, bowler identity, or measurement accuracy.";
  }
  return matched[0];
}

function validationText(matched: string[]): string {
  const blob = matched.join(" ").toLowerCase();
  const parts: string[] = [];
  if (/visibility is not landmark accuracy|missing score is not landmark accuracy|no cutoff was applied/.test(blob)) {
    parts.push(
      "Visibility and presence are model scores, not landmark accuracy. A missing score is not accuracy, and no cutoff was applied.",
    );
  }
  if (/not as zero|not zero degrees/.test(blob)) {
    parts.push("A missing pose or angle is unavailable, not zero degrees.");
  }
  if (/no manual reference angle|no accuracy statistic/.test(blob)) {
    parts.push("No reference angle and no accuracy statistic is included.");
  }
  return parts.join(" ") || matched[0];
}

function uniqueStrings(values: unknown[]): string[] {
  const seen: string[] = [];
  for (const value of values) {
    if (typeof value !== "string" || value.length === 0 || seen.includes(value)) continue;
    seen.push(value);
  }
  return seen;
}
