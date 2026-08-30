import type { HumanCapability } from "./authContract";

export const ROUTES = {
  customerHome: "/help",
  customerLogin: "/help/login",
  internalHome: "/internal",
  internalLogin: "/internal/login",
  states: "/states",
  forbidden: "/403",
  notFound: "/404",
} as const;

const INTERNAL_ROUTE_PATHS = {
  support: "/internal/support",
  approvals: "/internal/approvals",
  knowledge: "/internal/knowledge",
} as const;

export const LEGACY_ROUTE_REDIRECTS = [
  { path: "/support", to: INTERNAL_ROUTE_PATHS.support, deprecated: true },
  { path: "/approver", to: INTERNAL_ROUTE_PATHS.approvals, deprecated: true },
] as const;

export type InternalWorkspace = {
  id: "support" | "approvals" | "knowledge";
  capability: HumanCapability;
  path: `/internal/${string}`;
  icon: string;
  menuLabel: string;
  cardLabel: string;
  eyebrow: string;
  description: string;
};

export const INTERNAL_WORKSPACES = [
  {
    id: "support",
    capability: "SUPPORT_WORKBENCH_ACCESS",
    path: INTERNAL_ROUTE_PATHS.support,
    icon: "服",
    menuLabel: "客服工作区",
    cardLabel: "客服工作区 · 调查与响应",
    eyebrow: "SUPPORT",
    description: "进入共享队列，查看当前职责允许的客服工作入口。",
  },
  {
    id: "approvals",
    capability: "APPROVAL_WORKBENCH_ACCESS",
    path: INTERNAL_ROUTE_PATHS.approvals,
    icon: "审",
    menuLabel: "审批工作区",
    cardLabel: "审批工作区 · 补偿审查",
    eyebrow: "APPROVAL",
    description: "进入待审批队列，查看当前职责允许的补偿审查入口。",
  },
  {
    id: "knowledge",
    capability: "KNOWLEDGE_READ_ACCESS",
    path: INTERNAL_ROUTE_PATHS.knowledge,
    icon: "知",
    menuLabel: "知识目录",
    cardLabel: "知识目录 · 规则与引用",
    eyebrow: "KNOWLEDGE",
    description: "检索真实版本化中文知识，查看适用范围与可追溯引用片段。",
  },
] as const satisfies readonly InternalWorkspace[];

export function internalWorkspace(id: InternalWorkspace["id"]) {
  const workspace = INTERNAL_WORKSPACES.find((entry) => entry.id === id);
  if (!workspace) throw new Error(`unknown internal workspace: ${id}`);
  return workspace;
}
