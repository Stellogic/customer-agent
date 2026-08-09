import { useEffect, useState } from "react";

type StatusProjection = {
  status: "UP" | "DEGRADED";
  services: Record<"spring" | "database" | "agent", "UP" | "DOWN">;
};

export function App() {
  const [projection, setProjection] = useState<StatusProjection | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/system/status", { signal: controller.signal, credentials: "same-origin" })
      .then((response) => {
        if (!response.ok) throw new Error("status request failed");
        return response.json() as Promise<StatusProjection>;
      })
      .then(setProjection)
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) setFailed(true);
      });
    return () => controller.abort();
  }, []);

  return (
    <main>
      <p className="eyebrow">LOCAL LEARNING BASELINE</p>
      <h1>客服工单调查与补偿审批 Agent</h1>
      <p className="lede">当前页面只读取 Spring Boot 提供的最小状态投影，不连接私有 Agent Server。</p>
      <section aria-live="polite" className="status-card">
        <span className={`signal ${projection?.status === "UP" ? "up" : "pending"}`} />
        <div>
          <strong>{failed ? "基线不可用" : projection?.status === "UP" ? "全栈基线已就绪" : "正在确认服务状态"}</strong>
          <p>{failed ? "请运行本地冒烟检查并查看服务日志。" : "React → Spring Boot → 私有 Agent Server / PostgreSQL"}</p>
        </div>
      </section>
    </main>
  );
}

