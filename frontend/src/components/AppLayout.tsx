import type { ReactNode } from "react";
import { Link } from "react-router-dom";

type AppLayoutProps = {
  children: ReactNode;
};

export function AppLayout({ children }: AppLayoutProps) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>
          <Link to="/">Fast Bowling Biomechanics Analysis</Link>
        </h1>
        <p>Local prototype for one side-on delivery video. Upload and inspection come before any measurement.</p>
      </header>
      <main>{children}</main>
    </div>
  );
}
