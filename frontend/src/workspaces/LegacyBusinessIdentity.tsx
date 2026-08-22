import { useEffect, useState, type ReactNode } from "react";

type SyntheticRole = "SUPPORT" | "APPROVER";
type SyntheticIdentity = { id: string; role: SyntheticRole };

export function LegacyBusinessIdentity({
  role,
  allowedIds,
  deniedTitle,
  children,
}: {
  role: SyntheticRole;
  allowedIds: readonly string[];
  deniedTitle: string;
  children: (id: string) => ReactNode;
}) {
  const [identity, setIdentity] = useState<SyntheticIdentity | null>();

  useEffect(() => {
    let active = true;
    void fetch("/api/demo/session", { credentials: "same-origin", cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("legacy business identity required");
        const value = (await response.json()) as unknown;
        if (!isSyntheticIdentity(value) || value.role !== role || !allowedIds.includes(value.id)) {
          throw new Error("legacy business identity role mismatch");
        }
        if (active) setIdentity(value);
      })
      .catch(() => {
        if (active) setIdentity(null);
      });
    return () => {
      active = false;
    };
  }, [allowedIds, role]);

  if (identity === undefined) {
    return (
      <main className="route-state">
        <p role="status">正在确认既有业务身份…</p>
      </main>
    );
  }
  if (identity === null) {
    return (
      <main className="route-state">
        <h1>{deniedTitle}</h1>
        <p>路由 Session 只驱动页面体验；本票未迁移业务 API 的既有合成身份来源。</p>
      </main>
    );
  }
  return children(identity.id);
}

function isSyntheticIdentity(value: unknown): value is SyntheticIdentity {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const identity = value as Record<string, unknown>;
  return (
    Object.keys(identity).every((key) => ["id", "role", "label"].includes(key)) &&
    typeof identity.id === "string" &&
    (identity.role === "SUPPORT" || identity.role === "APPROVER")
  );
}
