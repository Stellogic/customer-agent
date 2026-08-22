import type { CurrentSession, HumanCapability } from "./authContract";
import { INTERNAL_WORKSPACES, ROUTES } from "./workspaceRegistry";

export type { CurrentSession, HumanCapability } from "./authContract";

const RETURNABLE_PATHS = new Set<string>([
  ROUTES.customerHome,
  ROUTES.internalHome,
  ...INTERNAL_WORKSPACES.map((workspace) => workspace.path),
]);

export function hasCapability(session: CurrentSession, capability: HumanCapability) {
  return session.capabilities.includes(capability);
}

export function defaultPathFor(session: CurrentSession) {
  if (session.subjectType === "CUSTOMER") return ROUTES.customerHome;
  const available = INTERNAL_WORKSPACES.filter((workspace) =>
    hasCapability(session, workspace.capability),
  );
  return available.length === 1 ? available[0].path : ROUTES.internalHome;
}

export function loginPathFor(pathname: string) {
  return pathname.startsWith(ROUTES.internalHome) ? ROUTES.internalLogin : ROUTES.customerLogin;
}

export function safeReturnTo(value: string | null) {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return undefined;
  try {
    const target = new URL(value, globalThis.location.origin);
    if (target.origin !== globalThis.location.origin || target.hash) return undefined;
    if (!RETURNABLE_PATHS.has(target.pathname)) return undefined;
    return `${target.pathname}${target.search}`;
  } catch {
    return undefined;
  }
}
