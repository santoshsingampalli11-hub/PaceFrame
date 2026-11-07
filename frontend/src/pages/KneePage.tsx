import { Component, type ReactNode } from "react";
import { ErrorNotice } from "../components/ErrorNotice";
import { KneeMeasurementPanel } from "../components/KneeMeasurementPanel";
import { useDeliverySession } from "./useDeliverySession";

export function KneePage() {
  const { session, error, loading } = useDeliverySession();

  return (
    <>
      <h1>Knee Kinematics</h1>
      {loading ? <p role="status">Loading session…</p> : null}
      <ErrorNotice message={error} />
      {session ? (
        <MeasurementBoundary>
          <KneeMeasurementPanel session={session} />
        </MeasurementBoundary>
      ) : null}
    </>
  );
}

class MeasurementBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return <p role="alert">The measurement could not be shown.</p>;
    }
    return this.props.children;
  }
}
