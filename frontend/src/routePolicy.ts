export type HumanRole = "CUSTOMER" | "SUPPORT" | "APPROVER";
export type HumanCapability =
  "CUSTOMER_HELP_ACCESS" | "SUPPORT_WORKBENCH_ACCESS" | "APPROVAL_WORKBENCH_ACCESS";

export type CurrentSession = {
  id: string;
  displayName: string;
  subjectType: "CUSTOMER" | "INTERNAL";
  roles: HumanRole[];
  capabilities: HumanCapability[];
};

const RETURNABLE_PATHS = new Set([
  "/help",
  "/internal",
  "/internal/support",
  "/internal/approvals",
]);

export function hasCapability(session: CurrentSession, capability: HumanCapability) {
  return session.capabilities.includes(capability);
}

export function defaultPathFor(session: CurrentSession) {
  if (session.subjectType === "CUSTOMER") return "/help";
  const support = hasCapability(session, "SUPPORT_WORKBENCH_ACCESS");
  const approval = hasCapability(session, "APPROVAL_WORKBENCH_ACCESS");
  if (support && approval) return "/internal";
  if (support) return "/internal/support";
  if (approval) return "/internal/approvals";
  return "/internal";
}

export function loginPathFor(pathname: string) {
  return pathname.startsWith("/internal") ? "/internal/login" : "/help/login";
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
