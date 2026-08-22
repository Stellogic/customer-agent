import { useEffect, useRef, useState } from "react";
import {
  consumeSseEvents,
  hasOnlyKeys,
  isRecord,
  parseViewCursor,
  type SseEvent,
} from "./streamProtocol";
import { loadCsrfToken } from "./csrf";
import { humanSessionFetch } from "./humanSessionLifecycle";

const APPROVAL_SCHEMA = "approval-view-v1" as const;

type QueueItem = {
  proposalRevisionId: string;
  compensationMethod: string;
  amount: number;
  submittedAt: string;
  expiresAt: string;
};

type Lease = {
  proposalRevisionId: string;
  leaseToken: string;
  leaseVersion: number;
  expiresAt: string;
};
type ApprovalSnapshot = {
  view: "APPROVAL_VIEW";
  schema: typeof APPROVAL_SCHEMA;
  cursor: string;
  proposalRevisionId: string;
  proposalRevision: number;
  contentDigest: string;
  orderReference: string;
  reasonCode: string;
  compensationMethod: string;
  proposedAmount: number;
  authoritativeAmount: number;
  policyVersion: string;
  eligibilityChecks: string[];
  evidenceReferences: string[];
  evidenceSnapshot: Record<string, unknown>;
  leaseToken: string;
  leaseVersion: number;
  leaseExpiresAt: string;
  proposalExpiresAt: string;
};

export function ApprovalWorkbench() {
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [snapshot, setSnapshot] = useState<ApprovalSnapshot | null>(null);
  const [status, setStatus] = useState("正在读取待审批队列…");
  const streamController = useRef<AbortController | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const activeLease = useRef<Lease | null>(null);

  useEffect(() => {
    globalThis.history.replaceState(null, "", "/internal/approvals");
    void loadQueue();
    return () => {
      streamController.current?.abort();
      if (reconnectTimer.current !== null) globalThis.clearTimeout(reconnectTimer.current);
    };
  }, []);

  async function loadQueue() {
    try {
      const response = await humanSessionFetch("/api/approver/compensation-proposals", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error("queue unavailable");
      const value = (await response.json()) as unknown;
      if (!Array.isArray(value) || !value.every(isQueueItem)) throw new Error("invalid queue");
      setQueue(value);
      setStatus("待审批队列已刷新");
    } catch {
      setStatus("待审批队列暂时不可用");
    }
  }

  async function claim(revisionId: string) {
    streamController.current?.abort();
    setStatus("正在领取审批责任…");
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `/api/approver/compensation-proposals/${revisionId}/claims`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            [csrf.headerName]: csrf.token,
            "Content-Type": "application/json",
            "Idempotency-Key": globalThis.crypto.randomUUID(),
          },
          body: JSON.stringify({ requestedLeaseSeconds: 900 }),
        },
      );
      if (!response.ok) throw new Error("claim rejected");
      const lease = (await response.json()) as unknown;
      if (!isLease(lease)) throw new Error("invalid lease");
      activeLease.current = lease;
      globalThis.history.replaceState(null, "", `/internal/approvals?revision=${revisionId}`);
      await loadApprovalView(lease);
    } catch {
      revokeLocalAuthority("审批责任不可用，已返回队列。");
    }
  }

  async function loadApprovalView(lease: Lease) {
    try {
      const response = await humanSessionFetch(
        `/api/approver/compensation-proposals/${lease.proposalRevisionId}/approval-view`,
        {
          headers: leaseHeaders(lease),
          credentials: "same-origin",
          cache: "no-store",
        },
      );
      if (!response.ok) {
        revokeLocalAuthority("审批责任已结束，证据和操作已移除。");
        return;
      }
      const value = (await response.json()) as unknown;
      if (
        !isApprovalSnapshot(value) ||
        value.leaseToken !== lease.leaseToken ||
        value.leaseVersion !== lease.leaseVersion ||
        value.proposalRevisionId !== lease.proposalRevisionId
      ) {
        throw new Error("incompatible approval snapshot");
      }
      setSnapshot(value);
      setStatus("审批证据已与 Spring 权威状态同步");
      void consumeEvents(lease, value.cursor);
    } catch {
      scheduleRecovery(lease);
    }
  }

  async function consumeEvents(lease: Lease, cursor: string) {
    const controller = new AbortController();
    streamController.current = controller;
    try {
      const response = await humanSessionFetch(
        `/api/approver/compensation-proposals/${lease.proposalRevisionId}/approval-view/events`,
        {
          headers: { ...leaseHeaders(lease), "Last-Event-ID": cursor, Accept: "text/event-stream" },
          credentials: "same-origin",
          cache: "no-store",
          signal: controller.signal,
        },
      );
      if (
        response.status === 401 ||
        response.status === 403 ||
        response.status === 404 ||
        response.status === 410
      ) {
        revokeLocalAuthority("审批责任已结束，证据和操作已移除。");
        return;
      }
      if (response.status === 409) {
        await loadApprovalView(lease);
        return;
      }
      if (!response.ok) throw new Error("stream unavailable");
      const compatible = await consumeSseEvents(response.body, (event) => {
        if (!validEvent(event, lease, cursor)) return false;
        cursor = event.id;
        return true;
      });
      if (!compatible) {
        controller.abort();
        await loadApprovalView(lease);
        return;
      }
      scheduleRecovery(lease);
    } catch {
      if (!controller.signal.aborted) scheduleRecovery(lease);
    }
  }

  function scheduleRecovery(lease: Lease) {
    if (activeLease.current?.leaseToken !== lease.leaseToken || reconnectTimer.current !== null)
      return;
    setSnapshot(null);
    globalThis.history.replaceState(null, "", "/internal/approvals");
    setStatus("审批连接已断开；正在按当前租约重新校验权威快照…");
    reconnectTimer.current = globalThis.setTimeout(() => {
      reconnectTimer.current = null;
      if (activeLease.current?.leaseToken === lease.leaseToken) void loadApprovalView(lease);
    }, 250);
  }

  async function decide(decision: "approve" | "reject") {
    const lease = activeLease.current;
    if (!snapshot || !lease) return;
    const body =
      decision === "approve"
        ? {
            proposalRevision: snapshot.proposalRevision,
            contentDigest: snapshot.contentDigest,
            internalNote: "符合当前审批证据",
          }
        : {
            proposalRevision: snapshot.proposalRevision,
            contentDigest: snapshot.contentDigest,
            internalReason: "需要人工复核",
          };
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `/api/approver/compensation-proposals/${lease.proposalRevisionId}/${decision}`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            ...leaseHeaders(lease),
            [csrf.headerName]: csrf.token,
            "Content-Type": "application/json",
            "Idempotency-Key": globalThis.crypto.randomUUID(),
          },
          body: JSON.stringify(body),
        },
      );
      if (!response.ok) throw new Error("decision rejected");
      revokeLocalAuthority("审批责任已结束，已返回队列。");
      await loadQueue();
      setStatus("审批责任已结束，已返回队列。");
    } catch {
      revokeLocalAuthority("审批责任已失效，证据和操作已移除。");
    }
  }

  async function release() {
    const lease = activeLease.current;
    if (!lease) return;
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `/api/approver/compensation-proposals/${lease.proposalRevisionId}/release`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            ...leaseHeaders(lease),
            [csrf.headerName]: csrf.token,
            "Idempotency-Key": globalThis.crypto.randomUUID(),
          },
        },
      );
      if (!response.ok) throw new Error("release rejected");
      revokeLocalAuthority("审批责任已释放，已返回队列。");
      await loadQueue();
      setStatus("审批责任已释放，已返回队列。");
    } catch {
      revokeLocalAuthority("审批责任已失效，证据和操作已移除。");
    }
  }

  function revokeLocalAuthority(message: string) {
    streamController.current?.abort();
    streamController.current = null;
    if (reconnectTimer.current !== null) globalThis.clearTimeout(reconnectTimer.current);
    reconnectTimer.current = null;
    activeLease.current = null;
    setSnapshot(null);
    setStatus(message);
    globalThis.history.replaceState(null, "", "/internal/approvals");
  }

  return (
    <main className="support-workbench" aria-label="审批工作台">
      <header className="workbench-header">
        <div>
          <p className="eyebrow">APPROVAL VIEW</p>
          <h1>{snapshot ? "补偿提案审批" : "待审批补偿"}</h1>
        </div>
        <p role="status">{status}</p>
      </header>
      {snapshot ? (
        <section className="queue-panel" aria-label="当前审批视图">
          <h2>{snapshot.orderReference}</h2>
          <p>权威金额：¥{snapshot.authoritativeAmount}</p>
          <p>政策：{snapshot.policyVersion}</p>
          <h3>审批证据引用</h3>
          <ul>
            {snapshot.evidenceReferences.map((reference) => (
              <li key={reference}>{reference}</li>
            ))}
          </ul>
          <div className="ticket-actions">
            <button type="button" onClick={() => void release()}>
              释放审批
            </button>
            <button type="button" onClick={() => void decide("approve")}>
              批准补偿
            </button>
            <button type="button" onClick={() => void decide("reject")}>
              驳回并转人工
            </button>
          </div>
        </section>
      ) : (
        <section className="queue-panel">
          <h2>待审批补偿</h2>
          {queue.length ? (
            <ul className="queue-list">
              {queue.map((item) => (
                <li key={item.proposalRevisionId}>
                  <span>
                    {item.compensationMethod} · ¥{item.amount}
                  </span>
                  <button type="button" onClick={() => void claim(item.proposalRevisionId)}>
                    领取审批
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p>当前没有待审批提案</p>
          )}
        </section>
      )}
    </main>
  );

  function leaseHeaders(lease: Lease) {
    return {
      "X-Approval-Lease-Token": lease.leaseToken,
      "X-Approval-Lease-Version": String(lease.leaseVersion),
    };
  }
}

function isQueueItem(value: unknown): value is QueueItem {
  return (
    isRecord(value) &&
    isUuid(value.proposalRevisionId) &&
    typeof value.compensationMethod === "string" &&
    typeof value.amount === "number" &&
    typeof value.submittedAt === "string" &&
    typeof value.expiresAt === "string"
  );
}
function isLease(value: unknown): value is Lease {
  return (
    isRecord(value) &&
    isUuid(value.proposalRevisionId) &&
    isUuid(value.leaseToken) &&
    Number.isSafeInteger(value.leaseVersion) &&
    Number(value.leaseVersion) > 0 &&
    typeof value.expiresAt === "string"
  );
}
function isApprovalSnapshot(value: unknown): value is ApprovalSnapshot {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "view",
      "schema",
      "cursor",
      "proposalRevisionId",
      "proposalRevision",
      "contentDigest",
      "orderReference",
      "reasonCode",
      "delayHours",
      "delaySeconds",
      "compensationMethod",
      "proposedAmount",
      "authoritativeAmount",
      "policyVersion",
      "policyTier",
      "eligibilityChecks",
      "evidenceReferences",
      "evidenceSnapshot",
      "responsibilityChain",
      "leaseToken",
      "leaseVersion",
      "leaseExpiresAt",
      "submittedAt",
      "proposalExpiresAt",
    ]) ||
    value.view !== "APPROVAL_VIEW" ||
    value.schema !== APPROVAL_SCHEMA ||
    typeof value.cursor !== "string" ||
    parseCursor(value.cursor) === null ||
    !isUuid(value.proposalRevisionId) ||
    !isUuid(value.leaseToken) ||
    !Number.isSafeInteger(value.leaseVersion) ||
    !Array.isArray(value.evidenceReferences) ||
    !value.evidenceReferences.every((entry) => typeof entry === "string") ||
    !Array.isArray(value.eligibilityChecks) ||
    !value.eligibilityChecks.every((entry) => typeof entry === "string") ||
    !Array.isArray(value.responsibilityChain) ||
    !isRecord(value.evidenceSnapshot)
  )
    return false;
  return (
    typeof value.orderReference === "string" &&
    typeof value.policyVersion === "string" &&
    typeof value.compensationMethod === "string" &&
    typeof value.authoritativeAmount === "number" &&
    Number.isSafeInteger(value.proposalRevision) &&
    typeof value.contentDigest === "string"
  );
}
function validEvent(event: SseEvent, lease: Lease, cursor: string) {
  const current = parseCursor(cursor);
  const next = parseCursor(event.id);
  if (!current || !next) return false;
  if (next.sequence <= current.sequence) return true;
  if (next.sequence !== current.sequence + 1) return false;
  try {
    const envelope = JSON.parse(event.data) as unknown;
    if (
      !isRecord(envelope) ||
      !hasOnlyKeys(envelope, ["view", "schema", "payload"]) ||
      envelope.view !== "APPROVAL_VIEW" ||
      envelope.schema !== APPROVAL_SCHEMA ||
      !isRecord(envelope.payload) ||
      !hasOnlyKeys(envelope.payload, ["proposalRevisionId", "leaseVersion", "authorityState"])
    )
      return false;
    return (
      event.type === "APPROVAL_AUTHORITY_STARTED" &&
      envelope.payload.proposalRevisionId === lease.proposalRevisionId &&
      envelope.payload.leaseVersion === lease.leaseVersion &&
      envelope.payload.authorityState === "ACTIVE"
    );
  } catch {
    return false;
  }
}
function parseCursor(value: string) {
  return parseViewCursor(value, APPROVAL_SCHEMA);
}
function isUuid(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
}
