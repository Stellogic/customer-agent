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

const SUPPORT_SCHEMA = "support-workbench-v1" as const;
const lifecycleStates = [
  "NEW",
  "INVESTIGATING",
  "WAITING_FOR_CUSTOMER",
  "WAITING_FOR_EXTERNAL",
  "RESOLVED",
  "CLOSED",
] as const;
const handlingModes = ["AGENT", "HUMAN"] as const;
type LifecycleState = (typeof lifecycleStates)[number];
type HandlingMode = (typeof handlingModes)[number];

type QueueItem = {
  ticketId: string;
  lifecycleState: LifecycleState;
  handlingMode: HandlingMode;
  enteredAt: string;
};

type WorkbenchSnapshot = {
  view: "SUPPORT_WORKBENCH";
  schema: typeof SUPPORT_SCHEMA;
  cursor: string;
  sharedQueue: QueueItem[];
  escalationQueue: QueueItem[];
};

type EventEnvelope = {
  view: "SUPPORT_WORKBENCH";
  schema: typeof SUPPORT_SCHEMA;
  payload: unknown;
};
type QueueUpsert = QueueItem & { sharedEnteredAt: string; escalationEnteredAt: string | null };

type TicketDetails = {
  ticketId: string;
  customerId: string;
  orderReference: string;
  description: string;
  lifecycleState: LifecycleState;
  handlingMode: HandlingMode;
  publicConversation: Array<{ author: string; body: string; sentAt: string }>;
  investigationFacts: Array<{
    factType: string;
    factValue: string;
    evidenceReference: string;
    recordedAt: string;
  }>;
  businessTimeline: Array<{ eventType: string; actorId: string; occurredAt: string }>;
};

export function SupportWorkbench() {
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [connection, setConnection] = useState<
    "loading" | "syncing" | "resetting" | "live" | "stale"
  >("loading");
  const [details, setDetails] = useState<TicketDetails | null>(null);
  const [claimingTicketId, setClaimingTicketId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const snapshotRef = useRef<WorkbenchSnapshot | null>(null);
  const streamController = useRef<AbortController | null>(null);
  const reconnectTimer = useRef<number | null>(null);

  useEffect(() => {
    void loadSnapshot("loading");
    return () => {
      streamController.current?.abort();
      if (reconnectTimer.current !== null) globalThis.clearTimeout(reconnectTimer.current);
    };
  }, []);

  async function loadSnapshot(status: "loading" | "syncing" | "resetting" = "syncing") {
    streamController.current?.abort();
    if (reconnectTimer.current !== null) globalThis.clearTimeout(reconnectTimer.current);
    reconnectTimer.current = null;
    setConnection(status);
    try {
      const response = await humanSessionFetch("/api/support/workbench/snapshot", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error("snapshot request failed");
      const authoritative = (await response.json()) as unknown;
      if (!isSnapshot(authoritative)) throw new Error("incompatible snapshot");
      snapshotRef.current = authoritative;
      setSnapshot(authoritative);
      setConnection("live");
      void consumeEvents(authoritative.cursor);
    } catch {
      setConnection("stale");
    }
  }

  async function consumeEvents(cursor: string) {
    const controller = new AbortController();
    streamController.current = controller;
    try {
      const response = await humanSessionFetch("/api/support/workbench/events", {
        headers: { "Last-Event-ID": cursor, Accept: "text/event-stream" },
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      });
      if (response.status === 409) {
        await recoverFromSnapshot(controller);
        return;
      }
      if (!response.ok) throw new Error("event stream failed");
      const compatible = await consumeSseEvents(response.body, applyEvent);
      if (!compatible) {
        await recoverFromSnapshot(controller);
        return;
      }
    } catch {
      // The last snapshot stays visible but is explicitly marked stale.
    }
    if (!controller.signal.aborted && streamController.current === controller) {
      snapshotRef.current = null;
      setSnapshot(null);
      setDetails(null);
      setConnection("syncing");
      reconnectTimer.current = globalThis.setTimeout(() => {
        reconnectTimer.current = null;
        if (streamController.current === controller) void loadSnapshot("syncing");
      }, 250);
    }
  }

  async function recoverFromSnapshot(controller: AbortController) {
    if (streamController.current !== controller) return;
    controller.abort();
    setConnection("resetting");
    await new Promise<void>((resolve) => globalThis.setTimeout(resolve, 0));
    await loadSnapshot("resetting");
  }

  function applyEvent(event: SseEvent) {
    const current = snapshotRef.current;
    if (!current) return false;
    const currentCursor = parseCursor(current.cursor);
    const eventCursor = parseCursor(event.id);
    if (!currentCursor || !eventCursor || eventCursor.epoch !== currentCursor.epoch) return false;
    if (eventCursor.sequence <= currentCursor.sequence) return true;
    if (eventCursor.sequence !== currentCursor.sequence + 1) return false;

    let envelope: EventEnvelope;
    try {
      envelope = JSON.parse(event.data) as EventEnvelope;
    } catch {
      return false;
    }
    if (
      !isRecord(envelope) ||
      !hasOnlyKeys(envelope, ["view", "schema", "payload"]) ||
      envelope.view !== "SUPPORT_WORKBENCH" ||
      envelope.schema !== SUPPORT_SCHEMA
    )
      return false;

    let next: WorkbenchSnapshot;
    if (event.type === "QUEUE_TICKET_REMOVED") {
      if (!isRemoval(envelope.payload)) return false;
      const payload = envelope.payload;
      next = {
        ...current,
        cursor: event.id,
        sharedQueue: current.sharedQueue.filter((item) => item.ticketId !== payload.ticketId),
        escalationQueue: current.escalationQueue.filter(
          (item) => item.ticketId !== payload.ticketId,
        ),
      };
    } else if (event.type === "QUEUE_TICKET_UPSERTED") {
      if (!isUpsert(envelope.payload)) return false;
      const item: QueueItem = {
        ticketId: envelope.payload.ticketId,
        lifecycleState: envelope.payload.lifecycleState,
        handlingMode: envelope.payload.handlingMode,
        enteredAt: envelope.payload.sharedEnteredAt,
      };
      next = {
        ...current,
        cursor: event.id,
        sharedQueue: upsertAndSort(current.sharedQueue, item),
        escalationQueue:
          envelope.payload.escalationEnteredAt === null
            ? current.escalationQueue.filter((entry) => entry.ticketId !== item.ticketId)
            : upsertAndSort(current.escalationQueue, {
                ...item,
                enteredAt: envelope.payload.escalationEnteredAt,
              }),
      };
    } else {
      return false;
    }
    snapshotRef.current = next;
    setSnapshot(next);
    return true;
  }

  async function claimTicket(ticketId: string) {
    setClaimingTicketId(ticketId);
    setActionError("");
    try {
      const csrf = await loadCsrfToken();
      const claim = await humanSessionFetch(`/api/support/workbench/tickets/${ticketId}/claims`, {
        method: "POST",
        credentials: "same-origin",
        headers: { [csrf.headerName]: csrf.token },
      });
      if (!claim.ok) throw new Error("claim rejected");
      const detailResponse = await humanSessionFetch(`/api/support/workbench/tickets/${ticketId}`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!detailResponse.ok) throw new Error("assigned detail unavailable");
      const value = (await detailResponse.json()) as unknown;
      if (!isTicketDetails(value)) throw new Error("incompatible detail");
      setDetails(value);
    } catch {
      setActionError("领取未完成或分配已失效；请重新同步队列后再试。");
    } finally {
      setClaimingTicketId(null);
    }
  }

  return (
    <main className="support-workbench" aria-label="客服工作台">
      <header className="workbench-header">
        <div>
          <p className="eyebrow">SUPPORT WORKBENCH</p>
          <h1>客服共享队列</h1>
          <p className="lede">发现需要人工关注的客服工单；领取与完整人工处理不在当前切片中。</p>
        </div>
        <div
          className={`connection-state ${connection}`}
          role={connection === "stale" || connection === "resetting" ? "alert" : "status"}
          aria-live="polite"
        >
          {connection === "loading" && "正在读取权威快照…"}
          {connection === "syncing" && "正在从 Spring 权威快照重新同步…"}
          {connection === "resetting" && "事件流已失效；当前队列可能过期，正在重新读取权威快照…"}
          {connection === "live" && "队列已与 Spring 权威状态同步"}
          {connection === "stale" && "实时连接已断开；当前队列可能过期。"}
        </div>
      </header>

      <p className="authorization-note">队列可发现不等于工单详情授权</p>

      <div
        className="queue-grid"
        aria-busy={
          connection === "loading" || connection === "syncing" || connection === "resetting"
        }
      >
        <QueueSection
          title="待接手工单"
          description="转人工与其他共享队列条目"
          items={snapshot?.sharedQueue ?? []}
          claimingTicketId={claimingTicketId}
          onClaim={claimTicket}
        />
        <QueueSection
          title="SLA 违约升级"
          description="已发生 SLA 违约、需要提高关注的工单"
          items={snapshot?.escalationQueue ?? []}
          claimingTicketId={claimingTicketId}
          onClaim={claimTicket}
          accent
        />
      </div>

      {actionError && (
        <p className="error" role="alert">
          {actionError}
        </p>
      )}

      {details && (
        <section className="ticket-card" aria-labelledby="support-ticket-detail-title">
          <h2 id="support-ticket-detail-title">当前工单详情</h2>
          <p>{details.ticketId}</p>
          <dl>
            <dt>订单编号</dt>
            <dd>{details.orderReference}</dd>
            <dt>问题描述</dt>
            <dd>{details.description}</dd>
            <dt>当前状态</dt>
            <dd>{stateLabel(details.lifecycleState)}</dd>
          </dl>
        </section>
      )}

      <footer className="workbench-footer">
        <p>快照游标与客户、审批视图相互独立；刷新不会沿用旧本地队列。</p>
        <button
          type="button"
          onClick={() => void loadSnapshot()}
          disabled={
            connection === "loading" || connection === "syncing" || connection === "resetting"
          }
        >
          重新同步队列
        </button>
      </footer>
    </main>
  );
}

function QueueSection({
  title,
  description,
  items,
  claimingTicketId,
  onClaim,
  accent = false,
}: {
  title: string;
  description: string;
  items: QueueItem[];
  claimingTicketId: string | null;
  onClaim: (ticketId: string) => Promise<void>;
  accent?: boolean;
}) {
  return (
    <section
      className={`queue-panel${accent ? " escalation" : ""}`}
      aria-labelledby={`${title}-title`}
    >
      <header>
        <div>
          <p className="queue-kicker">{accent ? "ESCALATION" : "SHARED"}</p>
          <h2 id={`${title}-title`}>{title}</h2>
          <p>{description}</p>
        </div>
        <strong aria-label={`${title}数量`}>{items.length.toString().padStart(2, "0")}</strong>
      </header>
      {items.length ? (
        <ul className="queue-list" aria-label={title}>
          {items.map((item) => (
            <li key={item.ticketId}>
              <div>
                <span className="ticket-number">{item.ticketId}</span>
                <span>
                  {stateLabel(item.lifecycleState)} ·{" "}
                  {item.handlingMode === "HUMAN" ? "人工处理" : "Agent 处理"}
                </span>
              </div>
              <time dateTime={item.enteredAt}>{formatTime(item.enteredAt)}</time>
              <button
                type="button"
                aria-label={`领取工单 ${item.ticketId}`}
                disabled={claimingTicketId !== null}
                onClick={() => void onClaim(item.ticketId)}
              >
                {claimingTicketId === item.ticketId ? "正在领取…" : "领取"}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-queue">当前没有队列条目</p>
      )}
    </section>
  );
}

function isSnapshot(value: unknown): value is WorkbenchSnapshot {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ["view", "schema", "cursor", "sharedQueue", "escalationQueue"]) ||
    value.view !== "SUPPORT_WORKBENCH" ||
    value.schema !== SUPPORT_SCHEMA ||
    typeof value.cursor !== "string" ||
    parseCursor(value.cursor) === null ||
    !Array.isArray(value.sharedQueue) ||
    !Array.isArray(value.escalationQueue)
  )
    return false;
  return value.sharedQueue.every(isQueueItem) && value.escalationQueue.every(isQueueItem);
}

function isQueueItem(value: unknown): value is QueueItem {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["ticketId", "lifecycleState", "handlingMode", "enteredAt"]) &&
    isTicketId(value.ticketId) &&
    isLifecycleState(value.lifecycleState) &&
    isHandlingMode(value.handlingMode) &&
    typeof value.enteredAt === "string"
  );
}

function isTicketDetails(value: unknown): value is TicketDetails {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "ticketId",
      "customerId",
      "orderReference",
      "description",
      "lifecycleState",
      "handlingMode",
      "publicConversation",
      "investigationFacts",
      "businessTimeline",
    ]) &&
    isTicketId(value.ticketId) &&
    typeof value.customerId === "string" &&
    typeof value.orderReference === "string" &&
    typeof value.description === "string" &&
    isLifecycleState(value.lifecycleState) &&
    isHandlingMode(value.handlingMode) &&
    Array.isArray(value.publicConversation) &&
    Array.isArray(value.investigationFacts) &&
    Array.isArray(value.businessTimeline)
  );
}

function isRemoval(value: unknown): value is { ticketId: string } {
  return isRecord(value) && hasOnlyKeys(value, ["ticketId"]) && isTicketId(value.ticketId);
}

function isUpsert(value: unknown): value is QueueUpsert {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "ticketId",
      "lifecycleState",
      "handlingMode",
      "sharedEnteredAt",
      "escalationEnteredAt",
    ]) &&
    isTicketId(value.ticketId) &&
    isLifecycleState(value.lifecycleState) &&
    isHandlingMode(value.handlingMode) &&
    typeof value.sharedEnteredAt === "string" &&
    (value.escalationEnteredAt === null || typeof value.escalationEnteredAt === "string")
  );
}

function isTicketId(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
}

function isLifecycleState(value: unknown): value is LifecycleState {
  return typeof value === "string" && lifecycleStates.some((state) => state === value);
}

function isHandlingMode(value: unknown): value is HandlingMode {
  return typeof value === "string" && handlingModes.some((mode) => mode === value);
}

function parseCursor(cursor: string) {
  return parseViewCursor(cursor, SUPPORT_SCHEMA);
}

function upsertAndSort(items: QueueItem[], item: QueueItem) {
  return [...items.filter((existing) => existing.ticketId !== item.ticketId), item].sort(
    (left, right) =>
      left.enteredAt.localeCompare(right.enteredAt) || left.ticketId.localeCompare(right.ticketId),
  );
}

function stateLabel(state: LifecycleState) {
  const labels: Record<LifecycleState, string> = {
    NEW: "新建",
    INVESTIGATING: "调查中",
    WAITING_FOR_CUSTOMER: "等待客户",
    WAITING_FOR_EXTERNAL: "等待外部信息",
    RESOLVED: "已解决",
    CLOSED: "已关闭",
  };
  return labels[state];
}

function formatTime(value: string) {
  const instant = new Date(value);
  return Number.isNaN(instant.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(instant);
}
