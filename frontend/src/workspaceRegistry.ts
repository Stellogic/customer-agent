import type { HumanCapability } from "./authContract";

export const ROUTES = {
  customerHome: "/help",
  customerLogin: "/help/login",
  internalHome: "/internal",
  internalLogin: "/internal/login",
} as const;

const INTERNAL_ROUTE_PATHS = {
  support: "/internal/support",
  approvals: "/internal/approvals",
} as const;

export const LEGACY_ROUTE_REDIRECTS = [
  { path: "/support", to: INTERNAL_ROUTE_PATHS.support, deprecated: true },
  { path: "/approver", to: INTERNAL_ROUTE_PATHS.approvals, deprecated: true },
] as const;

export type InternalWorkspace = {
  id: "support" | "approvals";
  capability: HumanCapability;
  path: `/internal/${string}`;
  menuLabel: string;
  cardLabel: string;
};

export const INTERNAL_WORKSPACES = [
  {
    id: "support",
    capability: "SUPPORT_WORKBENCH_ACCESS",
    path: INTERNAL_ROUTE_PATHS.support,
    menuLabel: "客服工作区",
    cardLabel: "客服工作区 · 调查与响应",
  },
  {
    id: "approvals",
    capability: "APPROVAL_WORKBENCH_ACCESS",
    path: INTERNAL_ROUTE_PATHS.approvals,
    menuLabel: "审批工作区",
    cardLabel: "审批工作区 · 补偿审查",
  },
] as const satisfies readonly InternalWorkspace[];

export function internalWorkspace(id: InternalWorkspace["id"]) {
  const workspace = INTERNAL_WORKSPACES.find((entry) => entry.id === id);
  if (!workspace) throw new Error(`unknown internal workspace: ${id}`);
  return workspace;
}
