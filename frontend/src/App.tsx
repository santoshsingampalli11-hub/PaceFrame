import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { EventsPage } from "./pages/EventsPage";
import { KneePage } from "./pages/KneePage";
import { ReportPage } from "./pages/ReportPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SessionPage } from "./pages/SessionPage";
import { UploadPage } from "./pages/UploadPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<UploadPage />} />
        <Route path="/sessions/:sessionId" element={<SessionPage />} />
        <Route path="/sessions/:sessionId/review" element={<ReviewPage />} />
        <Route path="/sessions/:sessionId/events" element={<EventsPage />} />
        <Route path="/sessions/:sessionId/knee" element={<KneePage />} />
        <Route path="/sessions/:sessionId/report" element={<ReportPage />} />
      </Route>
    </Routes>
  );
}
