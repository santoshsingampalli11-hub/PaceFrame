import { useEffect, useState } from "react";
import { ApiError, getHealth } from "../api/client";

type Status = "checking" | "ready" | "down";

export function BackendStatus() {
  const [status, setStatus] = useState<Status>("checking");
  const [message, setMessage] = useState("Checking the analysis server.");

  useEffect(() => {
    let active = true;
    getHealth()
      .then((health) => {
        if (!active) return;
        if (health.status === "healthy") {
          setStatus("ready");
          setMessage("Analysis server is running.");
        } else {
          setStatus("down");
          setMessage("The analysis server did not report a healthy status.");
        }
      })
      .catch((error: unknown) => {
        if (!active) return;
        setStatus("down");
        setMessage(error instanceof ApiError ? error.message : "The analysis server is not reachable.");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <p className="server-status" aria-live="polite">
      <span className={status === "ready" ? "status-ok" : status === "down" ? "status-bad" : undefined}>{message}</span>
    </p>
  );
}
