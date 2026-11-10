import type { KneeAngleResult, StoredMeasurement } from "../api/types";

/** Column order is fixed. Names match the stored measurement report. */
export const MEASUREMENT_CSV_COLUMNS = [
  "session_id",
  "bowler_id",
  "delivery_id",
  "phase",
  "frame_index",
  "front_leg",
  "angle_degrees",
  "measurement_status",
  "review_status",
  "warnings",
  "video_sha256",
  "label_provenance",
  "label_byte_identity_verified",
] as const;

/** Values in angle_degrees are decimal degrees. Full stored precision is kept. */
export const ANGLE_DEGREES_UNIT = "degrees";

const PHASES = [
  { phase: "FFC", key: "ffc" },
  { phase: "Release", key: "release" },
] as const;

const FORMULA_START = /^[\t\r\n\uFEFF ]*[=+\-@]/;

/**
 * One row for FFC and one row for Release.
 * angle_degrees is copied from the stored report. A missing angle stays blank.
 */
export function measurementCsv(sessionId: string, report: Partial<StoredMeasurement> | null | undefined): string {
  const rows = [MEASUREMENT_CSV_COLUMNS.join(","), ...PHASES.map((item) => phaseRow(sessionId, report, item.phase, item.key))];
  return `\uFEFF${rows.join("\r\n")}\r\n`;
}

/** Opaque session id only. Bowler and delivery names are not used in the file name. */
export function measurementCsvFilename(sessionId: string): string {
  const anonymous = /^[0-9a-f]{32}$/i.test(sessionId) ? sessionId.toLowerCase() : "session";
  return `${anonymous}-front-knee.csv`;
}

function phaseRow(
  sessionId: string,
  report: Partial<StoredMeasurement> | null | undefined,
  phase: "FFC" | "Release",
  key: "ffc" | "release",
): string {
  const angle = report?.[key];
  const degrees = angleCell(angle?.angle_degrees);
  const cells = [
    textCell(sessionId),
    textCell(report?.bowler_id),
    textCell(report?.delivery_id),
    textCell(phase),
    frameCell(angle?.frame_index),
    textCell(report?.front_leg),
    degrees,
    textCell(statusCell(degrees, angle?.status)),
    textCell(angle?.review_status),
    textCell(warningCell(report?.warnings, angle?.warnings)),
    textCell(report?.video_sha256),
    textCell(report?.annotation_provenance),
    flagCell(report?.annotation_byte_identity_verified),
  ];
  return cells.join(",");
}

function statusCell(degrees: string, status: KneeAngleResult["status"] | null | undefined): string {
  if (typeof status === "string" && status.length > 0) return status;
  if (degrees === "") return "unavailable";
  return "";
}

function warningCell(reportWarnings: unknown, phaseWarnings: unknown): string {
  const items: string[] = [];
  for (const source of [reportWarnings, phaseWarnings]) {
    if (!Array.isArray(source)) continue;
    for (const item of source) {
      if (typeof item !== "string" || item.length === 0) continue;
      if (!items.includes(item)) items.push(item);
    }
  }
  return items.join("; ");
}

function textCell(value: unknown): string {
  if (typeof value !== "string") return "";
  return csvField(neutralize(value));
}

function flagCell(value: unknown): string {
  if (value === true) return csvField("true");
  if (value === false) return csvField("false");
  return "";
}

function frameCell(value: unknown): string {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) return "";
  return String(value);
}

function angleCell(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  const printed = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(printed)) return "";
  return printed;
}

function neutralize(value: string): string {
  if (/^[\t\r]/.test(value) || FORMULA_START.test(value)) return `'${value}`;
  return value;
}

function csvField(value: string): string {
  if (/[",\r\n]/.test(value)) return `"${value.replaceAll('"', '""')}"`;
  return value;
}
