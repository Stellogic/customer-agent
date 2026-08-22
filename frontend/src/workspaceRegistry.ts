import type { HumanCapability } from "./authContract";

export const ROUTES = {
  customerHome: "/help",
  customerLogin: "/help/login",
  internalHome: "/internal",
  internalLogin: "/internal/login",
} as const;

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
    path: "/internal/support",
    menuLabel: "客服工作区",
    cardLabel: "客服工作区 · 调查与响应",
  },
  {
    id: "approvals",
    capability: "APPROVAL_WORKBENCH_ACCESS",
    path: "/internal/approvals",
    menuLabel: "审批工作区",
    cardLabel: "审批工作区 · 补偿审查",
  },
] as const satisfies readonly InternalWorkspace[];

export function internalWorkspace(id: InternalWorkspace["id"]) {
  const workspace = INTERNAL_WORKSPACES.find((entry) => entry.id === id);
  if (!workspace) throw new Error(`unknown internal workspace: ${id}`);
  return workspace;
}
