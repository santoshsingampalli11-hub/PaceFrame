import { FormEvent, useEffect, useState } from "react";
import { ApiError, getSessionLabels, saveSessionLabels } from "../api/client";
import type { SessionLabels } from "../api/types";

export type EventDraft = {
  bfc: number | null;
  ffc: number | null;
  release: number | null;
};

type ManualEventAnnotationPanelProps = {
  sessionId: string;
  frameCount: number;
  displayedFrame: number | null;
  knownFrontLeg: string | null;
  onShowFrame: (index: number) => void;
};

export function ManualEventAnnotationPanel({
  sessionId,
  frameCount,
  displayedFrame,
  knownFrontLeg,
  onShowFrame,
}: ManualEventAnnotationPanelProps) {
  const [draft, setDraft] = useState<EventDraft>({ bfc: null, ffc: null, release: null });
  const [saved, setSaved] = useState<SessionLabels | null>(null);
  const [labelsError, setLabelsError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);
  const [frontLeg, setFrontLeg] = useState<"" | "left" | "right">(
    knownFrontLeg === "left" || knownFrontLeg === "right" ? knownFrontLeg : "",
  );
  const [confirmFrontLeg, setConfirmFrontLeg] = useState(false);
  const [confirmLabelLink, setConfirmLabelLink] = useState(false);
  const [labeler, setLabeler] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    getSessionLabels(sessionId)
      .then((labels) => {
        if (!active) return;
        setSaved(labels);
        setLabelsError(null);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setSaved(null);
        setLabelsError(
          caught instanceof ApiError ? caught.message : "Saved labels could not be read. They are not shown as verified.",
        );
      });
    return () => {
      active = false;
    };
  }, [sessionId]);

  const locked = saved !== null;
  const canMark = displayedFrame !== null && !locked && !saving;

  function mark(eventName: keyof EventDraft) {
    if (displayedFrame === null || locked) return;
    setDraft((current) => ({ ...current, [eventName]: displayedFrame }));
    setSavedNotice(null);
  }

  async function onSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (locked || saving) return;
    const problem = validateEventDraft(draft, frameCount, frontLeg, confirmFrontLeg, confirmLabelLink, labeler);
    if (problem) {
      setSaveError(problem);
      return;
    }
    if (knownFrontLeg && frontLeg !== knownFrontLeg) {
      setSaveError(`This session already records front leg ${knownFrontLeg}. It was not changed.`);
      return;
    }
    if (draft.ffc === null || draft.release === null || (frontLeg !== "left" && frontLeg !== "right")) return;
    setSaving(true);
    setSaveError(null);
    try {
      const stored = await saveSessionLabels(sessionId, {
        bfc_frame: draft.bfc,
        ffc_frame: draft.ffc,
        release_frame: draft.release,
        front_leg: frontLeg,
        confirm_front_leg: confirmFrontLeg,
        confirm_label_link: confirmLabelLink,
        labeler: labeler.trim(),
        notes: "",
      });
      setSaved(stored);
      setSavedNotice("Labels saved.");
    } catch (caught: unknown) {
      setSavedNotice(null);
      setSaveError(caught instanceof ApiError ? caught.message : "The labels could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel annotation-panel" aria-label="Manual events">
      <h2>Manual events</h2>
      <p className="hint">
        Mark the frame that is on screen. BFC is optional. FFC and Release are required before a later measurement.
        Nothing is detected automatically, and nothing is saved until you press Save labels.
      </p>
      <p className="displayed-frame">
        Displayed frame: <strong>{displayedFrame === null ? "not loaded" : displayedFrame}</strong>
      </p>
      {!locked && displayedFrame === null ? (
        <p className="hint">Marking is available once the requested frame image has finished loading.</p>
      ) : null}
      {labelsError ? <p role="alert">{labelsError}</p> : null}
      {locked && saved ? <SavedLabels labels={saved} onShowFrame={onShowFrame} /> : null}
      {!locked ? (
        <form onSubmit={onSave}>
          <div className="frame-controls">
            <button type="button" disabled={!canMark} onClick={() => mark("bfc")}>
              Mark BFC
            </button>
            <button type="button" disabled={!canMark} onClick={() => mark("ffc")}>
              Mark FFC
            </button>
            <button type="button" disabled={!canMark} onClick={() => mark("release")}>
              Mark Release
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft({ bfc: null, ffc: null, release: null });
                setSavedNotice(null);
              }}
            >
              Clear unsaved selection
            </button>
          </div>
          <EventSummary
            draft={draft}
            onShowFrame={onShowFrame}
            onClear={(eventName) => {
              setDraft((current) => ({ ...current, [eventName]: null }));
              setSavedNotice(null);
            }}
          />
          <label htmlFor="front-leg-choice">
            Anatomical front leg
            <select
              id="front-leg-choice"
              value={frontLeg}
              onChange={(event) => setFrontLeg(event.target.value as "" | "left" | "right")}
            >
              <option value="">Not selected</option>
              <option value="left">Left</option>
              <option value="right">Right</option>
            </select>
          </label>
          <p className="hint">Left and right are the bowler&apos;s sides. The picture does not decide this.</p>
          <label htmlFor="confirm-front-leg">
            <input
              id="confirm-front-leg"
              type="checkbox"
              checked={confirmFrontLeg}
              onChange={(event) => setConfirmFrontLeg(event.target.checked)}
            />
            I confirm this front leg
          </label>
          <label htmlFor="confirm-label-link">
            <input
              id="confirm-label-link"
              type="checkbox"
              checked={confirmLabelLink}
              onChange={(event) => setConfirmLabelLink(event.target.checked)}
            />
            I confirm these labels belong to this video
          </label>
          <p className="hint">
            That confirmation is a human check. It is not a cryptographic proof of the filename sidecar.
          </p>
          <label htmlFor="labeler-id">
            Labeler id
            <input id="labeler-id" value={labeler} autoComplete="off" onChange={(event) => setLabeler(event.target.value)} />
          </label>
          {saveError ? <p role="alert">{saveError}</p> : null}
          <button type="submit" disabled={saving}>
            {saving ? "Saving labels…" : "Save labels"}
          </button>
        </form>
      ) : null}
      {savedNotice ? <p role="status">{savedNotice}</p> : null}
    </section>
  );
}

function EventSummary({
  draft,
  onShowFrame,
  onClear,
}: {
  draft: EventDraft;
  onShowFrame: (index: number) => void;
  onClear: (eventName: keyof EventDraft) => void;
}) {
  return (
    <ul className="event-summary" aria-label="Unsaved event frames">
      <EventLine name="BFC" eventName="bfc" index={draft.bfc} onShowFrame={onShowFrame} onClear={onClear} />
      <EventLine name="FFC" eventName="ffc" index={draft.ffc} onShowFrame={onShowFrame} onClear={onClear} />
      <EventLine name="Release" eventName="release" index={draft.release} onShowFrame={onShowFrame} onClear={onClear} />
    </ul>
  );
}

function EventLine({
  name,
  eventName,
  index,
  onShowFrame,
  onClear,
}: {
  name: string;
  eventName: keyof EventDraft;
  index: number | null;
  onShowFrame: (index: number) => void;
  onClear: (eventName: keyof EventDraft) => void;
}) {
  return (
    <li>
      Unsaved {name}: {index === null ? "not marked" : index}
      {index !== null ? (
        <>
          <button type="button" onClick={() => onShowFrame(index)}>
            Show {name}
          </button>
          <button type="button" onClick={() => onClear(eventName)}>
            Clear {name}
          </button>
        </>
      ) : null}
    </li>
  );
}

function SavedLabels({ labels, onShowFrame }: { labels: SessionLabels; onShowFrame: (index: number) => void }) {
  return (
    <div>
      <p role="status">Labels are already saved for this session. Replacing them is not available here.</p>
      <dl className="facts">
        <dt>Saved BFC</dt>
        <dd>{labels.bfc_frame === null ? "not marked" : labels.bfc_frame}</dd>
        <dt>Saved FFC</dt>
        <dd>{labels.ffc_frame}</dd>
        <dt>Saved Release</dt>
        <dd>{labels.release_frame}</dd>
        <dt>Front leg</dt>
        <dd>{labels.front_leg}</dd>
        <dt>Front leg confirmed</dt>
        <dd>{labels.confirm_front_leg ? "Yes" : "No"}</dd>
        <dt>Label link confirmed</dt>
        <dd>{labels.confirm_label_link ? "Yes" : "No"}</dd>
      </dl>
      <p className="hint">{labels.scientific_caveat}</p>
      <div className="frame-controls">
        {labels.bfc_frame !== null ? (
          <button type="button" onClick={() => onShowFrame(labels.bfc_frame as number)}>
            Show saved BFC
          </button>
        ) : null}
        <button type="button" onClick={() => onShowFrame(labels.ffc_frame as number)}>
          Show saved FFC
        </button>
        <button type="button" onClick={() => onShowFrame(labels.release_frame as number)}>
          Show saved Release
        </button>
      </div>
    </div>
  );
}

export function validateEventDraft(
  draft: EventDraft,
  frameCount: number,
  frontLeg: string,
  confirmFrontLeg: boolean,
  confirmLabelLink: boolean,
  labeler: string,
): string | null {
  const last = frameCount - 1;
  if (draft.ffc === null) return "Mark FFC on the displayed frame before saving.";
  if (draft.release === null) return "Mark Release on the displayed frame before saving.";
  if (!inRange(draft.bfc, last) || !inRange(draft.ffc, last) || !inRange(draft.release, last)) {
    return "An event frame is outside the decoded video.";
  }
  if (draft.bfc !== null && draft.bfc >= draft.ffc) {
    return "BFC must be earlier than FFC. The frames were not reordered.";
  }
  if (draft.ffc >= draft.release) {
    return "FFC must be earlier than Release. The frames were not reordered.";
  }
  if (frontLeg !== "left" && frontLeg !== "right") return "Choose the bowler's left or right front leg.";
  if (!confirmFrontLeg) return "Confirm the front leg before saving.";
  if (!confirmLabelLink) return "Confirm these labels belong to this video before saving.";
  const trimmed = labeler.trim();
  if (!trimmed || /[/\\:]/.test(trimmed)) return "Enter a labeler id without a file path.";
  return null;
}

function inRange(index: number | null, last: number): boolean {
  return index === null || (Number.isInteger(index) && index >= 0 && index <= last);
}
