import { createContext, use } from "react";
import type { CurrentSession } from "./routePolicy";

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
  const response = await fetch("/api/auth/session", {
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
  const value = (await response.json()) as unknown;
  if (!isCurrentSession(value)) throw new Error("invalid session response");
  return value;
}

function isCurrentSession(value: unknown): value is CurrentSession {
  if (!isRecord(value)) return false;
  return (
    Object.keys(value).every((key) =>
      ["id", "displayName", "subjectType", "roles", "capabilities"].includes(key),
    ) &&
    typeof value.id === "string" &&
    typeof value.displayName === "string" &&
    (value.subjectType === "CUSTOMER" || value.subjectType === "INTERNAL") &&
    Array.isArray(value.roles) &&
    value.roles.every((entry) => ["CUSTOMER", "SUPPORT", "APPROVER"].includes(String(entry))) &&
    Array.isArray(value.capabilities) &&
    value.capabilities.every((entry) =>
      ["CUSTOMER_HELP_ACCESS", "SUPPORT_WORKBENCH_ACCESS", "APPROVAL_WORKBENCH_ACCESS"].includes(
        String(entry),
      ),
    )
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
