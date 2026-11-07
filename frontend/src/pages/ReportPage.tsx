import { ErrorNotice } from "../components/ErrorNotice";
import { ReportPanel } from "../components/ReportPanel";
import { useDeliverySession } from "./useDeliverySession";

export function ReportPage() {
  const { session, error, loading } = useDeliverySession();

  return (
    <>
      <h1>Analysis Report</h1>
      {loading ? <p role="status">Loading session…</p> : null}
      <ErrorNotice message={error} />
      {session ? <ReportPanel session={session} /> : null}
    </>
  );
}
