import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { ApiError, getSession } from "../api/client";
import type { SessionResponse } from "../api/types";

type DeliverySessionState = {
  session: SessionResponse | null;
  error: string | null;
  loading: boolean;
};

const DeliverySessionContext = createContext<DeliverySessionState | null>(null);

export function DeliverySessionProvider({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const state = useDeliverySessionState(sessionIdFromPath(pathname));
  return <DeliverySessionContext.Provider value={state}>{children}</DeliverySessionContext.Provider>;
}

export function useDeliverySession(): DeliverySessionState {
  const value = useContext(DeliverySessionContext);
  if (!value) {
    throw new Error("Session state is unavailable.");
  }
  return value;
}

function sessionIdFromPath(pathname: string): string {
  const match = pathname.match(/^\/sessions\/([^/]+)/);
  if (!match) return "";
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

function useDeliverySessionState(sessionId: string): DeliverySessionState {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(sessionId));

  useEffect(() => {
    let active = true;
    if (!/^[0-9a-f]{32}$/i.test(sessionId)) {
      setLoading(false);
      setSession(null);
      setError(sessionId ? "This session id is not valid." : null);
      return () => {
        active = false;
      };
    }
    setLoading(true);
    setError(null);
    setSession(null);
    getSession(sessionId)
      .then((loaded) => {
        if (active) setSession(loaded);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setSession(null);
        setError(caught instanceof ApiError ? caught.message : "The session could not be loaded.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [sessionId]);

  return { session, error, loading };
}
