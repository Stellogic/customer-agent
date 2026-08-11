import { useEffect, useState } from "react";
import { App } from "./App";
import { SupportWorkbench } from "./SupportWorkbench";

export function RootApplication() {
  return globalThis.location.pathname === "/support" ? <SupportRoute /> : <App />;
}

function SupportRoute() {
  const [supportId, setSupportId] = useState<string | null>();

  useEffect(() => {
    void fetch("/api/demo/session", { credentials: "same-origin", cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("support session required");
        const session = await response.json() as unknown;
        if (!isSupportSession(session)) throw new Error("support session required");
        setSupportId(session.id);
      })
      .catch(() => setSupportId(null));
  }, []);

  if (supportId === undefined) {
    return <main className="route-state"><p role="status">正在确认客服身份…</p></main>;
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
  return Object.keys(session).every((key) => ["id", "role", "label"].includes(key))
    && session.id === "support-demo" && session.role === "SUPPORT";
}
