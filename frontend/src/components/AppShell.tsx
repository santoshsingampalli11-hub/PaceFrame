import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { DeliverySessionProvider } from "../pages/useDeliverySession";
import { BackendStatus } from "./BackendStatus";

const STEPS = [
  { id: "01", label: "Upload & Session", suffix: "" },
  { id: "02", label: "Video & Pose Review", suffix: "/review" },
  { id: "03", label: "Event Annotation", suffix: "/events" },
  { id: "04", label: "Knee Kinematics", suffix: "/knee" },
  { id: "05", label: "Analysis Report", suffix: "/report" },
] as const;

export function AppShell() {
  const location = useLocation();
  const sessionMatch = location.pathname.match(/^\/sessions\/([0-9a-f]{32})(?:\/|$)/i);
  const sessionId = sessionMatch?.[1];
  const [menuOpen, setMenuOpen] = useState(false);
  const base = sessionId ? `/sessions/${sessionId}` : "";
  const current = STEPS.find((step) =>
    step.suffix === ""
      ? location.pathname === "/" || location.pathname === base
      : location.pathname.endsWith(step.suffix),
  );

  return (
    <DeliverySessionProvider>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <div className="lab">
        <aside id="workflow-menu" className={menuOpen ? "sidebar open" : "sidebar"}>
          <p className="brand">PaceFrame</p>
          <p className="brand-sub">Every Frame. Better Form.</p>
          <nav aria-label="Workflow">
            {STEPS.map((step) => {
              const href = step.suffix === "" ? base || "/" : `${base}${step.suffix}`;
              const disabled = step.suffix !== "" && !sessionId;
              if (disabled) {
                return (
                  <span key={step.id} className="nav-item disabled">
                    <span>{step.id}</span>
                    {step.label}
                  </span>
                );
              }
              return (
                <NavLink
                  key={step.id}
                  to={href}
                  end={step.suffix === ""}
                  className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
                  onClick={() => setMenuOpen(false)}
                >
                  <span>{step.id}</span>
                  {step.label}
                </NavLink>
              );
            })}
          </nav>
        </aside>
        <div className="lab-main">
          <header className="topbar">
            <button
              type="button"
              className="menu-button"
              aria-expanded={menuOpen}
              aria-controls="workflow-menu"
              onClick={() => setMenuOpen((open) => !open)}
            >
              {menuOpen ? "Close menu" : "Menu"}
            </button>
            <div>
              <p className="product-name">
                {current ? `${current.id} ${current.label}` : "Smartphone fast bowling biomechanics"}
              </p>
              <p className="session-ref">
                {sessionId ? (
                  <span title={sessionId}>Session {sessionId.slice(0, 8)}</span>
                ) : (
                  "No session yet"
                )}
              </p>
            </div>
            <BackendStatus />
            <ol className="stepper" aria-label="Workflow progress">
              {STEPS.map((step) => {
                const here =
                  step.suffix === ""
                    ? location.pathname === "/" || location.pathname === base
                    : location.pathname.endsWith(step.suffix);
                return (
                  <li key={step.id} className={here ? "current" : undefined} aria-current={here ? "step" : undefined}>
                    {step.id} {step.label}
                  </li>
                );
              })}
            </ol>
          </header>
          <main id="main-content" tabIndex={-1} key={location.pathname} className="route-stage">
            <Outlet />
          </main>
        </div>
      </div>
    </DeliverySessionProvider>
  );
}
