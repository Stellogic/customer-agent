import { createContext, use } from "react";
import { parseCurrentSession, type CurrentSession } from "./authContract";
import { humanSessionFetch } from "./humanSessionLifecycle";

const SessionContext = createContext<CurrentSession | null>(null);

export const CurrentSessionContext = {
  Provider: SessionContext.Provider,
  use() {
    const session = use(SessionContext);
    if (!session) throw new Error("current session required");
    return session;
  },
};

export async function loadOptionalCurrentSession(): Promise<CurrentSession | undefined> {
  const response = await humanSessionFetch("/api/auth/session", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (response.status === 401) return undefined;
  if (!response.ok) throw new Error("session unavailable");
  return readCurrentSession(response);
}

export async function loadCurrentSession(): Promise<CurrentSession> {
  const session = await loadOptionalCurrentSession();
  if (!session) throw new Error("session unavailable");
  return session;
}

async function readCurrentSession(response: Response): Promise<CurrentSession> {
  const session = parseCurrentSession(await response.json());
  if (!session) throw new Error("invalid session response");
  return session;
}
