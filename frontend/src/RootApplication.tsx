import { useEffect, useState } from "react";
import { App } from "./App";
import { SupportWorkbench } from "./SupportWorkbench";
import { ApprovalWorkbench } from "./ApprovalWorkbench";

export function RootApplication() {
  if (globalThis.location.pathname === "/support") return <SupportRoute />;
  if (globalThis.location.pathname === "/approver") return <ApproverRoute />;
  return <App />;
}

function ApproverRoute() {
  const [approverId, setApproverId] = useState<string | null>();
  useEffect(() => {
    void fetch("/api/demo/session", { credentials: "same-origin", cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("approver session required");
        const session = (await response.json()) as unknown;
        if (!isApproverSession(session)) throw new Error("approver session required");
        setApproverId(session.id);
      })
      .catch(() => setApproverId(null));
  }, []);
  if (approverId === undefined)
    return (
      <main className="route-state">
        <p role="status">正在确认审批人身份…</p>
      </main>
    );
  if (approverId === null)
    return (
      <main className="route-state">
        <h1>无权访问审批工作台</h1>
      </main>
    );
  return <ApprovalWorkbench approverId={approverId} />;
}

function SupportRoute() {
  const [supportId, setSupportId] = useState<string | null>();

  useEffect(() => {
    void fetch("/api/demo/session", { credentials: "same-origin", cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("support session required");
        const session = (await response.json()) as unknown;
        if (!isSupportSession(session)) throw new Error("support session required");
        setSupportId(session.id);
      })
      .catch(() => setSupportId(null));
  }, []);

  if (supportId === undefined) {
    return (
      <main className="route-state">
        <p role="status">正在确认客服身份…</p>
      </main>
    );
  }
  if (supportId === null) {
    return (
      <main className="route-state">
        <p className="eyebrow">SUPPORT WORKBENCH</p>
        <h1>无权访问客服工作台</h1>
        <p>此路由只为已由 Spring 注册的客服演示会话开放。</p>
      </main>
    );
  }
  return <SupportWorkbench supportId={supportId} />;
}

function isSupportSession(value: unknown): value is { id: string; role: "SUPPORT" } {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const session = value as Record<string, unknown>;
  return (
    Object.keys(session).every((key) => ["id", "role", "label"].includes(key)) &&
    session.id === "support-demo" &&
    session.role === "SUPPORT"
  );
}

function isApproverSession(value: unknown): value is { id: string; role: "APPROVER" } {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const session = value as Record<string, unknown>;
  return (
    Object.keys(session).every((key) => ["id", "role", "label"].includes(key)) &&
    ["approver-demo", "approver-other-demo"].includes(String(session.id)) &&
    session.role === "APPROVER"
  );
}
