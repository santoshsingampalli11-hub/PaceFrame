import type { StoredMeasurement } from "../api/types";
import { presentLimitations } from "./scientificLimitations";

type ScientificLimitationsProps = {
  measurement: StoredMeasurement;
};

export function ScientificLimitations({ measurement }: ScientificLimitationsProps) {
  const view = presentLimitations(measurement);
  if (view.groups.length === 0 && view.additional.length === 0) return null;
  return (
    <section className="panel" aria-label="Scientific limitations">
      <h2>Scientific limitations</h2>
      {view.groups.map((group) => (
        <div key={group.id}>
          <h3>{group.title}</h3>
          <p>{group.text}</p>
        </div>
      ))}
      {view.additional.length > 0 ? (
        <>
          <h3>Additional warnings</h3>
          <ul>
            {view.additional.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
