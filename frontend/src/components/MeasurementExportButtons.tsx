import type { StoredMeasurement } from "../api/types";
import { measurementCsv, measurementCsvFilename } from "../export/measurementCsv";

type MeasurementExportButtonsProps = {
  sessionId: string;
  bowlerId: string;
  deliveryId: string;
  measurement: StoredMeasurement | null;
};

export function MeasurementExportButtons({
  sessionId,
  bowlerId,
  deliveryId,
  measurement,
}: MeasurementExportButtonsProps) {
  function downloadJson() {
    if (!measurement) return;
    const blob = new Blob([JSON.stringify(measurement, null, 2)], { type: "application/json" });
    saveBlob(blob, `${bowlerId}_${deliveryId}_measurement.json`);
  }

  function downloadCsv() {
    if (!measurement) return;
    const blob = new Blob([measurementCsv(sessionId, measurement)], { type: "text/csv;charset=utf-8" });
    saveBlob(blob, measurementCsvFilename(sessionId));
  }

  return (
    <>
      <p className="hint">
        The CSV has one row for FFC and one row for Release. The row under the header states that angle_degrees is
        measured in degrees. A blank angle is unavailable, not zero.
      </p>
      <div className="export-actions">
        <button type="button" onClick={downloadCsv} disabled={!measurement}>
          Download CSV
        </button>
        <button type="button" onClick={downloadJson} disabled={!measurement}>
          Download JSON
        </button>
      </div>
    </>
  );
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
