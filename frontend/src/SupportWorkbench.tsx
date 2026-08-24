import { useEffect, useRef, useState, type ReactNode } from "react";
import { Modal } from "antd";
import {
  consumeSseEvents,
  hasOnlyKeys,
  isRecord,
  parseViewCursor,
  type SseEvent,
} from "./streamProtocol";
import { loadCsrfToken } from "./csrf";
import { StatusNotice } from "./components/SystemState";
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
  const [pendingClaimTicketId, setPendingClaimTicketId] = useState<string | null>(null);
  const [claimingTicketId, setClaimingTicketId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const snapshotRef = useRef<WorkbenchSnapshot | null>(null);
  const streamController = useRef<AbortController | null>(null);
  const detailStreamController = useRef<AbortController | null>(null);
  const reconnectTimer = useRef<number | null>(null);

  useEffect(() => {
    void loadSnapshot("loading");
    return () => {
      streamController.current?.abort();
      detailStreamController.current?.abort();
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
    detailStreamController.current?.abort();
    detailStreamController.current = null;
    setDetails(null);
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
      void monitorTicketAuthority(ticketId);
    } catch {
      setActionError("领取未完成或分配已失效；请重新同步队列后再试。");
    } finally {
      setClaimingTicketId(null);
    }
  }

  async function monitorTicketAuthority(ticketId: string) {
    const controller = new AbortController();
    detailStreamController.current = controller;
    try {
      const response = await humanSessionFetch(
        `/api/support/workbench/tickets/${ticketId}/events`,
        {
          credentials: "same-origin",
          cache: "no-store",
          headers: { Accept: "text/event-stream" },
          signal: controller.signal,
        },
      );
      if (!response.ok) throw new Error("assignment authority unavailable");
      await consumeSseEvents(response.body, () => false);
    } catch {
      // Re-read the assigned detail below; the cached detail is never kept on an uncertain stream.
    }
    if (controller.signal.aborted || detailStreamController.current !== controller) return;
    try {
      const response = await humanSessionFetch(`/api/support/workbench/tickets/${ticketId}`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error("assignment no longer current");
      const value = (await response.json()) as unknown;
      if (!isTicketDetails(value)) throw new Error("incompatible detail");
      setDetails(value);
      void monitorTicketAuthority(ticketId);
    } catch {
      setDetails(null);
      setActionError("客服分配已失效；旧工单详情已移除，请重新同步队列。");
    }
  }

  return (
    <main className="support-workbench" aria-label="客服工作台">
      <header className="workbench-header">
        <div>
          <p className="eyebrow">SUPPORT WORKBENCH</p>
          <h1>客服共享队列</h1>
          <p className="lede">比较真实队列摘要；确认领取后才会取得并展示受保护的工单详情。</p>
        </div>
        <StatusNotice
          className={`connection-state ${connection}`}
          tone={
            connection === "live"
              ? "success"
              : connection === "loading" || connection === "syncing"
                ? "busy"
                : "danger"
          }
          role={connection === "stale" || connection === "resetting" ? "alert" : "status"}
        >
          {connection === "loading" && "正在读取权威快照…"}
          {connection === "syncing" && "正在从 Spring 权威快照重新同步…"}
          {connection === "resetting" && "事件流已失效；当前队列可能过期，正在重新读取权威快照…"}
          {connection === "live" && "队列已与 Spring 权威状态同步"}
          {connection === "stale" && "实时连接已断开；当前队列可能过期。"}
        </StatusNotice>
      </header>

      <p className="authorization-note">队列可发现不等于工单详情授权</p>

      <div
        className={`support-workspace-layout${details ? " has-detail" : ""}`}
        aria-busy={
          connection === "loading" || connection === "syncing" || connection === "resetting"
        }
      >
        <div className="support-queues">
          <QueueSection
            title="待接手工单"
            description="转人工与其他共享队列条目"
            items={snapshot?.sharedQueue ?? []}
            claimingTicketId={claimingTicketId}
            onClaim={setPendingClaimTicketId}
          />
          <QueueSection
            title="SLA 违约升级"
            description="已发生 SLA 违约、需要提高关注的工单"
            items={snapshot?.escalationQueue ?? []}
            claimingTicketId={claimingTicketId}
            onClaim={setPendingClaimTicketId}
            accent
          />
        </div>

        {details ? (
          <TicketDetail details={details} onCopyError={setActionError} />
        ) : (
          <aside className="detail-placeholder" aria-label="授权详情等待区">
            <span aria-hidden="true">↳</span>
            <p className="eyebrow">AUTHORIZED DETAIL</p>
            <h2>领取后查看授权详情</h2>
            <p>
              领取前仅提供队列最小摘要。确认领取并取得当前有效客服工单分配后，这里才会显示客户、订单与调查信息。
            </p>
          </aside>
        )}
      </div>

      {actionError && (
        <p className="error" role="alert">
          {actionError}
        </p>
      )}

      <footer className="workbench-footer">
        <p>队列会从权威状态重新同步；刷新不会沿用旧本地数据。</p>
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

      <Modal
        open={pendingClaimTicketId !== null}
        title="确认领取工单"
        okText="确认领取"
        cancelText="取消"
        confirmLoading={claimingTicketId !== null}
        closable={claimingTicketId === null}
        mask={{ closable: claimingTicketId === null }}
        onCancel={() => setPendingClaimTicketId(null)}
        onOk={() => {
          if (!pendingClaimTicketId) return;
          const ticketId = pendingClaimTicketId;
          setPendingClaimTicketId(null);
          void claimTicket(ticketId);
        }}
      >
        <p>领取会建立你对该工单的当前客服分配责任，并在成功后请求受保护详情。</p>
        {pendingClaimTicketId && (
          <p className="claim-confirm-ticket">工单 {shortTicketId(pendingClaimTicketId)}</p>
        )}
      </Modal>
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
  onClaim: (ticketId: string) => void;
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
        <div className="queue-table-wrap">
          <table className="queue-table" aria-label={title}>
            <thead>
              <tr>
                <th scope="col">工单</th>
                <th scope="col">生命周期</th>
                <th scope="col">处理模式</th>
                <th scope="col">进入时间</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.ticketId}>
                  <td>
                    <TicketIdentifier ticketId={item.ticketId} compact />
                  </td>
                  <td>
                    <span
                      className={`status support-status status-${item.lifecycleState.toLowerCase()}`}
                    >
                      {stateLabel(item.lifecycleState)}
                    </span>
                  </td>
                  <td>{item.handlingMode === "HUMAN" ? "人工处理" : "Agent 处理"}</td>
                  <td>
                    <time dateTime={item.enteredAt}>{formatTime(item.enteredAt)}</time>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="queue-claim-action"
                      aria-label={`领取工单 ${item.ticketId}`}
                      disabled={claimingTicketId !== null}
                      onClick={() => onClaim(item.ticketId)}
                    >
                      {claimingTicketId === item.ticketId ? "正在领取…" : "领取"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty-queue">当前没有队列条目</p>
      )}
    </section>
  );
}

function TicketDetail({
  details,
  onCopyError,
}: {
  details: TicketDetails;
  onCopyError: (message: string) => void;
}) {
  return (
    <article className="support-ticket-detail" aria-labelledby="support-ticket-detail-title">
      <header className="support-detail-header">
        <div>
          <p className="eyebrow">CURRENT ASSIGNMENT</p>
          <h2 id="support-ticket-detail-title">授权工单详情</h2>
        </div>
        <TicketIdentifier ticketId={details.ticketId} onCopyError={onCopyError} />
      </header>

      <div className="support-detail-summary">
        <dl aria-label="工单基本信息">
          <div>
            <dt>客户标识</dt>
            <dd>{details.customerId}</dd>
          </div>
          <div>
            <dt>订单引用</dt>
            <dd>{details.orderReference}</dd>
          </div>
          <div>
            <dt>生命周期</dt>
            <dd>{stateLabel(details.lifecycleState)}</dd>
          </div>
          <div>
            <dt>处理模式</dt>
            <dd>{details.handlingMode === "HUMAN" ? "人工处理" : "Agent 处理"}</dd>
          </div>
        </dl>
        <section aria-labelledby="support-description-title">
          <h3 id="support-description-title">问题描述</h3>
          <p>{details.description}</p>
        </section>
      </div>

      <div className="support-detail-sections">
        <DetailSection
          eyebrow="CUSTOMER VISIBLE"
          title="公开沟通"
          empty="暂无公开沟通"
          items={details.publicConversation.map((message, index) => (
            <li key={`${message.sentAt}-${index}`} className="conversation-entry">
              <div>
                <strong>{message.author}</strong>
                <time dateTime={message.sentAt}>{formatTime(message.sentAt)}</time>
              </div>
              <p>{message.body}</p>
            </li>
          ))}
        />
        <DetailSection
          eyebrow="INTERNAL FACTS"
          title="调查事实"
          empty="暂无调查事实"
          items={details.investigationFacts.map((fact, index) => (
            <li key={`${fact.recordedAt}-${fact.factType}-${index}`} className="fact-entry">
              <div>
                <strong>{fact.factType}</strong>
                <time dateTime={fact.recordedAt}>{formatTime(fact.recordedAt)}</time>
              </div>
              <p>{fact.factValue}</p>
              <small>证据引用：{fact.evidenceReference}</small>
            </li>
          ))}
        />
        <DetailSection
          eyebrow="RESPONSIBILITY CHAIN"
          title="业务时间线"
          empty="暂无业务时间线"
          items={details.businessTimeline.map((event, index) => (
            <li key={`${event.occurredAt}-${event.eventType}-${index}`} className="timeline-entry">
              <span className="timeline-marker" aria-hidden="true" />
              <div>
                <strong>{event.eventType}</strong>
                <p>{event.actorId}</p>
                <time dateTime={event.occurredAt}>{formatTime(event.occurredAt)}</time>
              </div>
            </li>
          ))}
        />
      </div>
    </article>
  );
}

function DetailSection({
  eyebrow,
  title,
  empty,
  items,
}: {
  eyebrow: string;
  title: string;
  empty: string;
  items: ReactNode[];
}) {
  const id = `support-${title}`;
  return (
    <section className="support-detail-section" aria-labelledby={id}>
      <header>
        <p className="eyebrow">{eyebrow}</p>
        <h3 id={id}>{title}</h3>
      </header>
      {items.length ? <ol>{items}</ol> : <p className="detail-empty">{empty}</p>}
    </section>
  );
}

function TicketIdentifier({
  ticketId,
  compact = false,
  onCopyError,
}: {
  ticketId: string;
  compact?: boolean;
  onCopyError?: (message: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await globalThis.navigator.clipboard.writeText(ticketId);
      setCopied(true);
    } catch {
      onCopyError?.("完整工单 UUID 复制失败，请稍后再试。");
    }
  }

  return (
    <span className={`support-ticket-identifier${compact ? " compact" : ""}`}>
      <span className="ticket-number">{shortTicketId(ticketId)}</span>
      <button
        type="button"
        aria-label={`复制完整工单 UUID ${ticketId}`}
        onClick={() => void copy()}
      >
        {copied ? "已复制" : "复制"}
      </button>
    </span>
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
    value.publicConversation.every(isConversationMessage) &&
    Array.isArray(value.investigationFacts) &&
    value.investigationFacts.every(isInvestigationFact) &&
    Array.isArray(value.businessTimeline) &&
    value.businessTimeline.every(isTimelineEvent)
  );
}

function isConversationMessage(
  value: unknown,
): value is TicketDetails["publicConversation"][number] {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["author", "body", "sentAt"]) &&
    typeof value.author === "string" &&
    typeof value.body === "string" &&
    typeof value.sentAt === "string"
  );
}

function isInvestigationFact(value: unknown): value is TicketDetails["investigationFacts"][number] {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["factType", "factValue", "evidenceReference", "recordedAt"]) &&
    typeof value.factType === "string" &&
    typeof value.factValue === "string" &&
    typeof value.evidenceReference === "string" &&
    typeof value.recordedAt === "string"
  );
}

function isTimelineEvent(value: unknown): value is TicketDetails["businessTimeline"][number] {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["eventType", "actorId", "occurredAt"]) &&
    typeof value.eventType === "string" &&
    typeof value.actorId === "string" &&
    typeof value.occurredAt === "string"
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

function shortTicketId(ticketId: string) {
  return `${ticketId.slice(0, 8)}…${ticketId.slice(-4)}`;
}
