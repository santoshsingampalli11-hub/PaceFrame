import { FormEvent, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, MAX_UPLOAD_BYTES, createSession } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { LimitationBanner } from "../components/LimitationBanner";

const ALLOWED_EXTENSIONS = [".mp4", ".mov", ".avi"];

type FieldErrors = {
  video?: string;
  bowlerId?: string;
  deliveryId?: string;
};

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadPage() {
  const navigate = useNavigate();
  const busy = useRef(false);
  const [file, setFile] = useState<File | null>(null);
  const [bowlerId, setBowlerId] = useState("B01");
  const [deliveryId, setDeliveryId] = useState("D01");
  const [frontLeg, setFrontLeg] = useState<"" | "left" | "right">("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function validate(): FieldErrors {
    const errors: FieldErrors = {};
    if (!file) {
      errors.video = "Choose a video file before uploading.";
    } else if (!ALLOWED_EXTENSIONS.includes(extensionOf(file.name))) {
      errors.video = "Use a .mp4, .mov, or .avi file. The server still checks that the file decodes.";
    } else if (file.size > MAX_UPLOAD_BYTES) {
      errors.video = "This file is larger than the server limit of 80 MiB. It was not sent.";
    }
    if (!/^B\d{2,}$/.test(bowlerId.trim())) {
      errors.bowlerId = "Use an anonymous id such as B01.";
    }
    if (!/^D\d{2,}$/.test(deliveryId.trim())) {
      errors.deliveryId = "Use an anonymous id such as D01.";
    }
    return errors;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    const errors = validate();
    setFieldErrors(errors);
    setFormError(null);
    if (Object.keys(errors).length > 0 || !file) return;

    busy.current = true;
    setSubmitting(true);
    try {
      const session = await createSession({
        video: file,
        bowlerId,
        deliveryId,
        frontLeg,
      });
      navigate(`/sessions/${session.session_id}`);
    } catch (error: unknown) {
      setFormError(error instanceof ApiError ? error.message : "The upload could not be sent.");
    } finally {
      busy.current = false;
      setSubmitting(false);
    }
  }

  return (
    <>
      <h1>Upload & Session</h1>
      <LimitationBanner />
      <form className="workspace" onSubmit={onSubmit} noValidate aria-describedby={formError ? "upload-error" : undefined}>
        <section className="panel">
          <h2>Video file</h2>
          <p className="hint">
            Supported containers: .mp4, .mov, .avi. Default server limit: 80 MiB. Choosing a file does not upload it.
            Client checks are hints; the server decides whether the file can be stored and decoded.
          </p>
          <ErrorNotice message={formError} id="upload-error" />
          <label htmlFor="video">
            Video file
            <input
              id="video"
              name="video"
              type="file"
              accept=".mp4,.mov,.avi,video/mp4,video/quicktime,video/x-msvideo"
              aria-invalid={Boolean(fieldErrors.video)}
              aria-describedby="video-hint video-error"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setFieldErrors((current) => ({ ...current, video: undefined }));
              }}
            />
          </label>
          <p id="video-hint" className="hint">
            {file
              ? `Selected locally: ${file.name} (${formatBytes(file.size)}). Not uploaded yet.`
              : "No file selected."}
          </p>
          {fieldErrors.video ? (
            <p id="video-error" className="field-error">
              {fieldErrors.video}
            </p>
          ) : null}
          {submitting ? <p role="status">Uploading… The server is receiving the file.</p> : null}
        </section>
        <section className="panel">
          <h2>Delivery identity</h2>
          <label htmlFor="bowler-id">
            Bowler id
            <input
              id="bowler-id"
              name="bowler_id"
              value={bowlerId}
              autoComplete="off"
              aria-invalid={Boolean(fieldErrors.bowlerId)}
              aria-describedby="bowler-error"
              onChange={(event) => setBowlerId(event.target.value)}
            />
          </label>
          {fieldErrors.bowlerId ? (
            <p id="bowler-error" className="field-error">
              {fieldErrors.bowlerId}
            </p>
          ) : null}

          <label htmlFor="delivery-id">
            Delivery id
            <input
              id="delivery-id"
              name="delivery_id"
              value={deliveryId}
              autoComplete="off"
              aria-invalid={Boolean(fieldErrors.deliveryId)}
              aria-describedby="delivery-error"
              onChange={(event) => setDeliveryId(event.target.value)}
            />
          </label>
          {fieldErrors.deliveryId ? (
            <p id="delivery-error" className="field-error">
              {fieldErrors.deliveryId}
            </p>
          ) : null}

          <label htmlFor="front-leg">
            Anatomical front leg
            <select
              id="front-leg"
              name="front_leg"
              value={frontLeg}
              onChange={(event) => setFrontLeg(event.target.value as "" | "left" | "right")}
            >
              <option value="">Not selected</option>
              <option value="left">Left</option>
              <option value="right">Right</option>
            </select>
          </label>
          <p className="hint">Optional. Left and right are the bowler&apos;s sides, not the sides of the picture.</p>
          <p className="hint">
            Record the delivery from the side, with the whole body in frame. This page does not calibrate the camera or
            check that the view is side-on.
          </p>
          <button type="submit" disabled={submitting}>
            {submitting ? "Uploading…" : "Upload and create session"}
          </button>
        </section>
      </form>
    </>
    );
}
