import { describe, expect, it } from "vitest";
import type { StoredMeasurement } from "../api/types";
import { ANGLE_DEGREES_UNIT, MEASUREMENT_CSV_COLUMNS, measurementCsv, measurementCsvFilename } from "./measurementCsv";

const sessionId = "ab".repeat(16);

function report(overrides: Partial<StoredMeasurement> = {}): StoredMeasurement {
  return {
    bowler_id: "B01",
    delivery_id: "D01",
    front_leg: "left",
    ffc_frame: 87,
    release_frame: 124,
    ffc: {
      frame_index: 87,
      angle_degrees: 142.5,
      status: "available",
      reason: "",
      review_status: "review_required",
      warnings: ['left_knee has no presence score. A missing score is not landmark accuracy, and no cutoff was applied.'],
      evidence: [],
    },
    release: {
      frame_index: 124,
      angle_degrees: null,
      status: "unavailable",
      reason: "No pose was detected.",
      review_status: "unavailable",
      warnings: [],
      evidence: [],
    },
    warnings: ["Side-on camera view is unconfirmed. That is not scientific approval."],
    limitations: ["These are 2D image-plane angles."],
    annotation_provenance: "human_confirmed_filename_sidecar",
    annotation_byte_identity_verified: false,
    video_sha256: "d".repeat(64),
    ...overrides,
  };
}

function rowsOf(csv: string): string[][] {
  const text = csv.startsWith("\uFEFF") ? csv.slice(1) : csv;
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"') {
      quoted = true;
      continue;
    }
    if (char === ",") {
      row.push(cell);
      cell = "";
      continue;
    }
    if (char === "\r") continue;
    if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      continue;
    }
    cell += char;
  }
  return rows;
}

describe("measurement CSV", () => {
  it("writes one header and one row each for FFC and Release, with degrees named on the angle column", () => {
    const csv = measurementCsv(sessionId, report());
    expect(csv.startsWith("\uFEFF")).toBe(true);
    expect(csv.endsWith("\r\n")).toBe(true);
    const rows = rowsOf(csv);
    expect(rows).toHaveLength(3);
    const angleIndex = MEASUREMENT_CSV_COLUMNS.indexOf("angle_degrees");
    expect(rows[0]).toEqual([...MEASUREMENT_CSV_COLUMNS]);
    expect(rows[0][angleIndex]).toBe("angle_degrees");
    expect(rows.filter((row) => row.length === 1 && row[0] === ANGLE_DEGREES_UNIT)).toEqual([]);

    const ffc = Object.fromEntries(MEASUREMENT_CSV_COLUMNS.map((column, index) => [column, rows[1][index]]));
    const release = Object.fromEntries(MEASUREMENT_CSV_COLUMNS.map((column, index) => [column, rows[2][index]]));
    expect(ffc).toMatchObject({
      session_id: sessionId,
      bowler_id: "B01",
      delivery_id: "D01",
      phase: "FFC",
      frame_index: "87",
      front_leg: "left",
      angle_degrees: "142.5",
      measurement_status: "available",
      review_status: "review_required",
      video_sha256: "d".repeat(64),
      label_provenance: "human_confirmed_filename_sidecar",
      label_byte_identity_verified: "false",
    });
    expect(ffc.warnings).toContain("Side-on camera view is unconfirmed.");
    expect(ffc.warnings).toContain("no cutoff was applied.");
    expect(release).toMatchObject({
      phase: "Release",
      frame_index: "124",
      angle_degrees: "",
      measurement_status: "unavailable",
      review_status: "unavailable",
      label_byte_identity_verified: "false",
    });
    expect(release.angle_degrees).not.toBe("0");
    expect(csv).not.toContain("video.avi");
    expect(csv).not.toContain("limitations");
  });

  it("keeps a stored zero and does not invent an angle, phase, or path", () => {
    const stored = report({
      ffc: { ...report().ffc, angle_degrees: 0, warnings: [], review_status: "no_structural_warning" },
    });
    const rows = rowsOf(measurementCsv(sessionId, stored));
    const angleIndex = MEASUREMENT_CSV_COLUMNS.indexOf("angle_degrees");
    expect(rows[1][angleIndex]).toBe("0");
    expect(rows[2][angleIndex]).toBe("");
    expect(rows.slice(1).map((row) => row[MEASUREMENT_CSV_COLUMNS.indexOf("phase")])).toEqual(["FFC", "Release"]);
    const withPath = measurementCsv(sessionId, {
      ...stored,
      video_filename: "C:\\videos\\bowler.mp4",
    } as StoredMeasurement);
    expect(withPath).not.toContain("videos");
    expect(withPath).not.toContain("bowler.mp4");
  });

  it("leaves optional fields blank and still marks a missing angle unavailable", () => {
    const rows = rowsOf(
      measurementCsv(sessionId, {
        ffc: { frame_index: null, angle_degrees: null, status: "", reason: "", review_status: "", warnings: [], evidence: [] },
        release: { frame_index: 4, angle_degrees: 90.25, status: "", reason: "", review_status: "", warnings: [], evidence: [] },
      }),
    );
    const ffc = rows[1];
    const release = rows[2];
    const column = (name: (typeof MEASUREMENT_CSV_COLUMNS)[number]) => MEASUREMENT_CSV_COLUMNS.indexOf(name);
    expect(ffc[column("bowler_id")]).toBe("");
    expect(ffc[column("delivery_id")]).toBe("");
    expect(ffc[column("frame_index")]).toBe("");
    expect(ffc[column("front_leg")]).toBe("");
    expect(ffc[column("angle_degrees")]).toBe("");
    expect(ffc[column("measurement_status")]).toBe("unavailable");
    expect(ffc[column("review_status")]).toBe("");
    expect(ffc[column("warnings")]).toBe("");
    expect(ffc[column("video_sha256")]).toBe("");
    expect(ffc[column("label_provenance")]).toBe("");
    expect(ffc[column("label_byte_identity_verified")]).toBe("");
    expect(release[column("frame_index")]).toBe("4");
    expect(release[column("angle_degrees")]).toBe("90.25");
    expect(release[column("measurement_status")]).toBe("");
    expect(rows).toHaveLength(3);
  });

  it("quotes commas, quotes, and newlines, and neutralizes formula text", () => {
    const rows = rowsOf(
      measurementCsv("=session", {
        bowler_id: "=1+1",
        delivery_id: '+cmd|" /c calc"!A0',
        front_leg: "@SUM(A1)",
        ffc: {
          frame_index: 2,
          angle_degrees: 10,
          status: "available",
          reason: "",
          review_status: " -1+1",
          warnings: ['He said "stop", then left', "line1\nline2"],
          evidence: [],
        },
        release: {
          frame_index: 3,
          angle_degrees: null,
          status: "unavailable",
          reason: "",
          review_status: "\t=1",
          warnings: [],
          evidence: [],
        },
        warnings: ["=HYPERLINK(\"http://evil\")"],
      }),
    );
    const column = (name: (typeof MEASUREMENT_CSV_COLUMNS)[number]) => MEASUREMENT_CSV_COLUMNS.indexOf(name);
    expect(rows[1][column("session_id")]).toBe("'=session");
    expect(rows[1][column("bowler_id")]).toBe("'=1+1");
    expect(rows[1][column("delivery_id")]).toBe('\'+cmd|" /c calc"!A0');
    expect(rows[1][column("front_leg")]).toBe("'@SUM(A1)");
    expect(rows[1][column("review_status")]).toBe("' -1+1");
    expect(rows[1][column("warnings")]).toBe('\'=HYPERLINK("http://evil"); He said "stop", then left; line1\nline2');
    expect(rows[2][column("review_status")]).toBe("'\t=1");
    expect(rows[1][column("angle_degrees")]).toBe("10");
    const raw = measurementCsv(sessionId, report({
      warnings: ['He said "stop", then left'],
      ffc: { ...report().ffc, warnings: [] },
    }));
    expect(raw).toContain('"He said ""stop"", then left"');
  });

  it("names the file from the anonymous session id", () => {
    expect(measurementCsvFilename(sessionId)).toBe(`${sessionId}-front-knee.csv`);
    expect(measurementCsvFilename(sessionId.toUpperCase())).toBe(`${sessionId}-front-knee.csv`);
    expect(measurementCsvFilename("B01_D01")).toBe("session-front-knee.csv");
    expect(measurementCsvFilename("../video.mp4")).toBe("session-front-knee.csv");
    expect(measurementCsvFilename("=cmd")).toBe("session-front-knee.csv");
  });
});
