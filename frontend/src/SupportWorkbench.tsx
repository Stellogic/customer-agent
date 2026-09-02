import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
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
import { IntakeAssistancePanel } from "./IntakeAssistancePanel";
import { SupportCompensationPanel } from "./SupportCompensationPanel";
import { SupportContextEntries } from "./components/internal/ContextEntries";
import { focusContextTarget } from "./components/internal/focusContextTarget";
import { SupportAssistance } from "./components/support-assistance/SupportAssistance";
import { clearPendingReply, readPendingReply, storePendingReply } from "./supportReplyStorage";

const SUPPORT_SCHEMA = "support-workbench-v2" as const;
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
  orderReference: string;
  issueKind: string;
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
  assignedTicketIds: string[];
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
  assignedSupportId?: string | null;
  publicConversation: Array<{
    messageId?: string | null;
    author: string;
    body: string;
    sentAt: string;
  }>;
  investigationFacts: Array<{
    factType: string;
    factValue: string;
    evidenceReference: string;
    recordedAt: string;
  }>;
  businessTimeline: Array<{ eventType: string; actorId: string; occurredAt: string }>;
};

type SupportPublicReplyResponse = {
  schema: typeof SUPPORT_SCHEMA;
  ticketId: string;
  messageId: string;
  publicMessageId: string;
  outcome: "ACCEPTED";
  accepted: true;
  replayed: boolean;
};

class SupportReplyUncertainError extends Error {}

class SupportReplyRejectedError extends Error {}

export function SupportWorkbench() {
  const [workspaceMode, setWorkspaceMode] = useState<"tickets" | "intake">("tickets");
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [connection, setConnection] = useState<
    "loading" | "syncing" | "resetting" | "live" | "stale"
  >("loading");
  const [details, setDetails] = useState<TicketDetails | null>(null);
  const [suspendedAssistanceTicket, setSuspendedAssistanceTicket] = useState<string | null>(null);
  const [pendingClaimTicketId, setPendingClaimTicketId] = useState<string | null>(null);
  const [claimingTicketId, setClaimingTicketId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const snapshotRef = useRef<WorkbenchSnapshot | null>(null);
  const streamController = useRef<AbortController | null>(null);
  const detailStreamController = useRef<AbortController | null>(null);
  const detailAuthorityGeneration = useRef(0);
  const snapshotRequestGeneration = useRef(0);
  const reconnectTimer = useRef<number | null>(null);

  useEffect(() => {
    void loadSnapshot("loading");
    return () => {
      streamController.current?.abort();
      detailStreamController.current?.abort();
      if (reconnectTimer.current !== null) globalThis.clearTimeout(reconnectTimer.current);
    };
  }, []);

  function invalidateDetailAuthority() {
    setSuspendedAssistanceTicket(null);
    detailAuthorityGeneration.current += 1;
    detailStreamController.current?.abort();
    detailStreamController.current = null;
    setDetails(null);
    return detailAuthorityGeneration.current;
  }

  async function loadSnapshot(status: "loading" | "syncing" | "resetting" = "syncing") {
    const generation = ++snapshotRequestGeneration.current;
    streamController.current?.abort();
    invalidateDetailAuthority();
    if (reconnectTimer.current !== null) globalThis.clearTimeout(reconnectTimer.current);
    reconnectTimer.current = null;
    setConnection(status);
    try {
      const response = await humanSessionFetch(
        "/api/support/workbench/snapshot?schema=support-workbench-v2",
        {
          credentials: "same-origin",
          cache: "no-store",
        },
      );
      if (!response.ok) throw new Error("snapshot request failed");
      const authoritative = (await response.json()) as unknown;
      if (!isSnapshot(authoritative)) throw new Error("incompatible snapshot");
      if (generation !== snapshotRequestGeneration.current) return;
      snapshotRef.current = authoritative;
      setSnapshot(authoritative);
      setConnection("live");
      void restoreAssignedDetails(authoritative.assignedTicketIds);
      void consumeEvents(authoritative.cursor);
    } catch {
      if (generation === snapshotRequestGeneration.current) setConnection("stale");
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
      invalidateDetailAuthority();
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
        orderReference: envelope.payload.orderReference,
        issueKind: envelope.payload.issueKind,
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
    const generation = invalidateDetailAuthority();
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
      const value = await readTicketDetails(ticketId);
      if (generation !== detailAuthorityGeneration.current) return;
      setDetails(value);
      setSnapshot((current) => {
        if (!current) return current;
        const assignedTicketIds = current.assignedTicketIds.includes(ticketId)
          ? current.assignedTicketIds
          : [...current.assignedTicketIds, ticketId];
        const next = { ...current, assignedTicketIds };
        snapshotRef.current = next;
        return next;
      });
      void monitorTicketAuthority(ticketId, generation);
    } catch {
      setActionError("领取未完成或分配已失效；请重新同步队列后再试。");
    } finally {
      setClaimingTicketId(null);
    }
  }

  async function restoreAssignedDetails(ticketIds: string[]) {
    const generation = invalidateDetailAuthority();
    if (ticketIds.length === 0) return;
    const preferred =
      details?.ticketId && ticketIds.includes(details.ticketId) ? details.ticketId : ticketIds[0];
    try {
      const value = await readTicketDetails(preferred);
      if (generation !== detailAuthorityGeneration.current) return;
      setDetails(value);
      void monitorTicketAuthority(preferred, generation);
    } catch {
      if (generation !== detailAuthorityGeneration.current) return;
      setDetails(null);
      setActionError("当前负责客服责任未能恢复；旧工单详情已清除，请重新同步。");
    }
  }

  async function openAssignedTicket(ticketId: string) {
    const generation = invalidateDetailAuthority();
    try {
      const value = await readTicketDetails(ticketId);
      if (generation !== detailAuthorityGeneration.current) return;
      setDetails(value);
      void monitorTicketAuthority(ticketId, generation);
    } catch {
      if (generation !== detailAuthorityGeneration.current) return;
      setDetails(null);
      setActionError("该工单的负责客服责任已失效；详情已清除，请重新同步。");
    }
  }

  async function releaseTicket(ticketId: string) {
    setActionError("");
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `/api/support/workbench/tickets/${ticketId}/release`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: { [csrf.headerName]: csrf.token },
        },
      );
      if (!response.ok) throw new Error("release rejected");
      invalidateDetailAuthority();
      await loadSnapshot("syncing");
    } catch {
      setActionError("释放领取未完成；请重新同步后再试。");
    }
  }

  async function readTicketDetails(ticketId: string) {
    const response = await humanSessionFetch(`/api/support/workbench/tickets/${ticketId}`, {
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!response.ok) throw new Error("assigned detail unavailable");
    const value = (await response.json()) as unknown;
    if (!isTicketDetails(value)) throw new Error("incompatible detail");
    return value;
  }

  async function sendPublicReply(ticketId: string, idempotencyKey: string, body: string) {
    let csrf: Awaited<ReturnType<typeof loadCsrfToken>>;
    try {
      csrf = await loadCsrfToken();
    } catch {
      throw new SupportReplyRejectedError("无法取得发送凭证，请稍后重试。");
    }

    let response: Response;
    try {
      response = await humanSessionFetch(`/api/support/workbench/tickets/${ticketId}/messages`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          [csrf.headerName]: csrf.token,
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify({ schema: SUPPORT_SCHEMA, message: body }),
      });
    } catch {
      throw new SupportReplyUncertainError(
        "发送结果暂未确认；请查询 Spring 权威结果，不要重复发送。",
      );
    }
    if (!response.ok && response.status < 500) {
      throw new SupportReplyRejectedError(
        response.status === 409
          ? "当前工单不允许发送公开回复，或人工处理责任已经失效。"
          : "公开回复未被接受，请确认当前客服责任后重试。",
      );
    }
    if (!response.ok) {
      throw new SupportReplyUncertainError(
        "发送结果暂未确认；请查询 Spring 权威结果，不要重复发送。",
      );
    }
    const result = await parseReplyResponse(response, ticketId, idempotencyKey);
    void refreshTicketDetails(ticketId);
    return result;
  }

  async function queryPublicReply(ticketId: string, idempotencyKey: string) {
    let response: Response;
    try {
      response = await humanSessionFetch(
        `/api/support/workbench/tickets/${ticketId}/messages/${encodeURIComponent(idempotencyKey)}`,
        { credentials: "same-origin", cache: "no-store" },
      );
    } catch {
      throw new SupportReplyUncertainError("仍无法连接 Spring；请稍后再次查询发送结果。");
    }
    if (response.status === 404) {
      throw new SupportReplyRejectedError("Spring 未找到该发送请求，可以安全重试公开回复。");
    }
    if (!response.ok) {
      throw new SupportReplyUncertainError("Spring 尚未返回可确认结果；请不要重新发送相同内容。");
    }
    const result = await parseReplyResponse(response, ticketId, idempotencyKey);
    void refreshTicketDetails(ticketId);
    return result;
  }

  async function parseReplyResponse(response: Response, ticketId: string, idempotencyKey: string) {
    try {
      const value = (await response.json()) as unknown;
      if (
        !isSupportReplyResponse(value) ||
        value.ticketId !== ticketId ||
        value.messageId !== idempotencyKey
      )
        throw new Error("incompatible reply response");
      return value;
    } catch {
      throw new SupportReplyUncertainError(
        "发送结果暂未确认；请查询 Spring 权威结果，不要重复发送。",
      );
    }
  }

  async function refreshTicketDetails(ticketId: string) {
    try {
      const value = await readTicketDetails(ticketId);
      setDetails((current) => (current?.ticketId === ticketId ? value : current));
    } catch {
      // The authority stream will clear the detail if the assignment changed meanwhile.
    }
  }

  async function monitorTicketAuthority(ticketId: string, generation: number) {
    if (generation !== detailAuthorityGeneration.current) return;
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
    if (
      controller.signal.aborted ||
      detailStreamController.current !== controller ||
      generation !== detailAuthorityGeneration.current
    )
      return;
    setSuspendedAssistanceTicket(ticketId);
    try {
      const value = await readTicketDetails(ticketId);
      if (generation !== detailAuthorityGeneration.current) return;
      setDetails((current) => (current?.ticketId === ticketId ? value : current));
      setSuspendedAssistanceTicket(null);
      void monitorTicketAuthority(ticketId, generation);
    } catch {
      if (generation !== detailAuthorityGeneration.current) return;
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

      <nav className="support-surface-tabs" aria-label="客服队列类型">
        <button
          type="button"
          aria-pressed={workspaceMode === "tickets"}
          onClick={() => setWorkspaceMode("tickets")}
        >
          客服工单队列
        </button>
        <button
          type="button"
          aria-pressed={workspaceMode === "intake"}
          onClick={() => setWorkspaceMode("intake")}
        >
          受理协助队列
        </button>
      </nav>

      {workspaceMode === "intake" ? (
        <IntakeAssistancePanel />
      ) : (
        <>
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
              <div className="support-assigned-detail">
                {(snapshot?.assignedTicketIds.length ?? 0) > 1 && (
                  <nav className="assigned-ticket-list" aria-label="已领取工单">
                    {snapshot?.assignedTicketIds.map((ticketId) => (
                      <button
                        key={ticketId}
                        type="button"
                        aria-pressed={details.ticketId === ticketId}
                        aria-label={`打开已领取工单 ${ticketId}`}
                        onClick={() => void openAssignedTicket(ticketId)}
                      >
                        {shortTicketId(ticketId)}
                      </button>
                    ))}
                  </nav>
                )}
                <TicketDetail
                  key={details.ticketId}
                  details={details}
                  assistanceAvailable={suspendedAssistanceTicket !== details.ticketId}
                  onCopyError={setActionError}
                  onSendReply={sendPublicReply}
                  onQueryReply={queryPublicReply}
                  onCompensationSubmitted={() => void refreshTicketDetails(details.ticketId)}
                  onRelease={() => void releaseTicket(details.ticketId)}
                />
              </div>
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
        </>
      )}
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
        <div className="order-grouped-queue">
          {groupQueueItems(items).map(([orderReference, orderItems]) => (
            <section
              className="support-order-group"
              aria-label={`订单 ${orderReference}`}
              key={orderReference}
            >
              <header>
                <span>订单工单组</span>
                <strong>{orderReference}</strong>
                <small>{orderItems.length} 张独立工单</small>
              </header>
              <div className="queue-table-wrap">
                <table className="queue-table" aria-label={title}>
                  <thead>
                    <tr>
                      <th scope="col">工单</th>
                      <th scope="col">问题</th>
                      <th scope="col">生命周期</th>
                      <th scope="col">处理模式</th>
                      <th scope="col">进入时间</th>
                      <th scope="col">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orderItems.map((item) => (
                      <tr key={item.ticketId}>
                        <td>
                          <TicketIdentifier ticketId={item.ticketId} compact />
                        </td>
                        <td>{issueKindLabel(item.issueKind)}</td>
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
                          {item.handlingMode === "HUMAN" ? (
                            <button
                              type="button"
                              className="queue-claim-action"
                              aria-label={`领取工单 ${item.ticketId}`}
                              disabled={claimingTicketId !== null}
                              onClick={() => onClaim(item.ticketId)}
                            >
                              {claimingTicketId === item.ticketId ? "正在领取…" : "领取"}
                            </button>
                          ) : (
                            <span className="queue-claim-unavailable">Agent 处理中</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      ) : (
        <p className="empty-queue">当前没有队列条目</p>
      )}
    </section>
  );
}

function TicketDetail({
  details,
  assistanceAvailable,
  onCopyError,
  onSendReply,
  onQueryReply,
  onCompensationSubmitted,
  onRelease,
}: {
  details: TicketDetails;
  assistanceAvailable: boolean;
  onCopyError: (message: string) => void;
  onSendReply: (
    ticketId: string,
    idempotencyKey: string,
    body: string,
  ) => Promise<SupportPublicReplyResponse>;
  onQueryReply: (ticketId: string, idempotencyKey: string) => Promise<SupportPublicReplyResponse>;
  onCompensationSubmitted: () => void;
  onRelease: () => void;
}) {
  const storedPendingReply = readPendingReply(details.ticketId);
  const orderRef = useRef<HTMLDivElement>(null);
  const replyRef = useRef<HTMLElement>(null);
  const factsRef = useRef<HTMLElement>(null);
  const assistanceRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState(() => storedPendingReply?.body ?? "");
  const [replyState, setReplyState] = useState<
    "idle" | "sending" | "unknown" | "querying" | "error"
  >(() => (storedPendingReply ? "unknown" : "idle"));
  const [pendingIdempotencyKey, setPendingIdempotencyKey] = useState<string | null>(
    () => storedPendingReply?.idempotencyKey ?? null,
  );
  const [replyNotice, setReplyNotice] = useState(() =>
    storedPendingReply ? "上次公开回复的发送结果尚未确认，请查询 Spring 权威结果。" : "",
  );
  const replyBusy = replyState === "sending" || replyState === "querying";
  const [reviewedAssistance, setReviewedAssistance] = useState<string | null>(null);
  const assistanceDraft = useRef<string | null>(null);
  const visibleDraft =
    !assistanceAvailable && assistanceDraft.current === draft ? "" : draft;
  const clearReviewedAssistance = useCallback(() => {
    setReviewedAssistance(null);
    const handedOffDraft = assistanceDraft.current;
    if (handedOffDraft !== null) {
      setDraft((current) => (current === handedOffDraft ? "" : current));
      assistanceDraft.current = null;
    }
  }, []);

  function reviewAssistance(text: string) {
    if (!assistanceAvailable || replyBusy || replyState === "unknown") return;
    if (draft.trim()) {
      setReviewedAssistance(text);
    } else {
      assistanceDraft.current = text;
      setDraft(text);
    }
  }

  async function submitReply() {
    const body = visibleDraft.trim();
    if (!body || replyState === "sending" || replyState === "querying") return;
    const idempotencyKey = createIdempotencyKey();
    setReviewedAssistance(null);
    storePendingReply(details.ticketId, { idempotencyKey, body });
    setPendingIdempotencyKey(idempotencyKey);
    setReplyState("sending");
    setReplyNotice("");
    try {
      await onSendReply(details.ticketId, idempotencyKey, body);
      clearPendingReply(details.ticketId);
      assistanceDraft.current = null;
      setDraft("");
      setPendingIdempotencyKey(null);
      setReplyState("idle");
      setReplyNotice("公开回复已由 Spring 保存并对客户可见。");
    } catch (error) {
      if (error instanceof SupportReplyUncertainError) {
        setReplyState("unknown");
        setReplyNotice(error.message);
      } else {
        clearPendingReply(details.ticketId);
        setPendingIdempotencyKey(null);
        setReplyState("error");
        setReplyNotice(error instanceof Error ? error.message : "公开回复未被接受，请稍后重试。");
      }
    }
  }

  async function queryReplyResult() {
    if (!pendingIdempotencyKey || replyState === "querying") return;
    setReplyState("querying");
    setReplyNotice("正在查询 Spring 权威发送结果…");
    try {
      await onQueryReply(details.ticketId, pendingIdempotencyKey);
      clearPendingReply(details.ticketId);
      assistanceDraft.current = null;
      setDraft("");
      setPendingIdempotencyKey(null);
      setReplyState("idle");
      setReplyNotice("已从 Spring 权威结果确认公开回复已保存。");
    } catch (error) {
      if (error instanceof SupportReplyRejectedError) {
        clearPendingReply(details.ticketId);
        setPendingIdempotencyKey(null);
        setReplyState("error");
        setReplyNotice(error.message);
        return;
      }
      setReplyState("unknown");
      setReplyNotice(
        error instanceof Error ? error.message : "仍无法确认发送结果，请稍后再次查询。",
      );
    }
  }

  return (
    <article className="support-ticket-detail" aria-labelledby="support-ticket-detail-title">
      <header className="support-detail-header">
        <div>
          <p className="eyebrow">CURRENT ASSIGNMENT</p>
          <h2 id="support-ticket-detail-title">授权工单详情</h2>
        </div>
        <div className="support-detail-header-actions">
          <TicketIdentifier ticketId={details.ticketId} onCopyError={onCopyError} />
          <button type="button" className="support-release-action" onClick={onRelease}>
            释放领取
          </button>
        </div>
      </header>

      <SupportContextEntries
        projectionKey={`${details.ticketId}:${details.assignedSupportId ?? ""}:${details.handlingMode}`}
        entries={{
          transfer: { kind: "developing" },
          more: { kind: "developing" },
          order: {
            kind: "available",
            onOpen: () => focusContextTarget(orderRef.current),
            description: "查看当前工单的订单引用，不额外读取订单详情。",
          },
          logistics: {
            kind: "available",
            onOpen: () => focusContextTarget(factsRef.current),
            description: "查看现有调查事实，是否含物流信息以当前投影为准。",
          },
          contact:
            details.handlingMode === "HUMAN"
              ? { kind: "available", onOpen: () => focusContextTarget(replyRef.current) }
              : { kind: "unavailable", reason: "当前非人工处理模式，不能发送公开回复。" },
          similarCases:
            details.handlingMode === "HUMAN" && assistanceAvailable
              ? {
                  kind: "available",
                  onOpen: () => focusContextTarget(assistanceRef.current),
                  description: "在当前工单的 AI 智能辅助中使用知识检索。",
                }
              : { kind: "unavailable", reason: "当前没有可用的人工辅助权限。" },
          suggestedActions:
            details.handlingMode === "HUMAN" && assistanceAvailable
              ? {
                  kind: "available",
                  onOpen: () => focusContextTarget(assistanceRef.current),
                  description: "在当前工单的 AI 智能辅助中查看建议。",
                }
              : { kind: "unavailable", reason: "当前没有可用的人工辅助权限。" },
        }}
      />

      <div className="support-detail-summary">
        <dl aria-label="工单基本信息">
          <div>
            <dt>客户标识</dt>
            <dd>{details.customerId}</dd>
          </div>
          <div ref={orderRef} tabIndex={-1} className="context-entry-target">
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
          <div>
            <dt>负责客服</dt>
            <dd>{details.assignedSupportId ?? "当前负责客服"}</dd>
          </div>
        </dl>
        <section aria-labelledby="support-description-title">
          <h3 id="support-description-title">问题描述</h3>
          <p>{details.description}</p>
        </section>
      </div>

      {details.handlingMode === "HUMAN" && (
        <section
          ref={replyRef}
          tabIndex={-1}
          className="support-reply-composer context-entry-target"
          aria-labelledby="support-reply-title"
        >
          <div className="support-reply-heading">
            <div>
              <p className="eyebrow">客户可见</p>
              <h3 id="support-reply-title">人工公开回复</h3>
            </div>
            <span>由当前客服责任授权</span>
          </div>
          <textarea
            aria-label="公开回复"
            value={visibleDraft}
            maxLength={2000}
            onChange={(event) => {
              assistanceDraft.current = null;
              setDraft(event.target.value);
              setReviewedAssistance(null);
            }}
            placeholder="写下客户可以看到的回复…"
            disabled={replyBusy || replyState === "unknown"}
            rows={4}
          />
          {reviewedAssistance !== null && !replyBusy && replyState !== "unknown" && (
            <div role="group" aria-label="确认替换人工发送区草稿">
              <p>发送区已有编辑内容，是否替换为已审阅辅助草稿？不会自动发送。</p>
              <button
                type="button"
                onClick={() => {
                  assistanceDraft.current = reviewedAssistance;
                  setDraft(reviewedAssistance);
                  setReviewedAssistance(null);
                }}
              >
                替换发送区草稿
              </button>
              <button type="button" onClick={() => setReviewedAssistance(null)}>
                保留发送区编辑
              </button>
            </div>
          )}
          <div className="support-reply-actions">
            <small>{visibleDraft.trim().length}/2000</small>
            <button
              type="button"
              onClick={() => void submitReply()}
              disabled={!visibleDraft.trim() || replyBusy || replyState === "unknown"}
            >
              {replyState === "sending" ? "正在发送…" : "发送公开回复"}
            </button>
          </div>
          {replyState === "unknown" && pendingIdempotencyKey && (
            <button
              type="button"
              className="support-reply-query"
              onClick={() => void queryReplyResult()}
              disabled={replyBusy}
            >
              查询发送结果
            </button>
          )}
          {replyNotice && (
            <p
              className={replyState === "error" ? "error" : "support-reply-notice"}
              role={replyState === "error" || replyState === "unknown" ? "alert" : "status"}
            >
              {replyNotice}
            </p>
          )}
        </section>
      )}

      {details.handlingMode === "HUMAN" && assistanceAvailable && (
        <SupportAssistance
          hostRef={assistanceRef}
          ticketId={details.ticketId}
          defaultQuery={details.description}
          onReviewDraft={replyBusy || replyState === "unknown" ? null : reviewAssistance}
          onClearDraft={clearReviewedAssistance}
        />
      )}

      {details.handlingMode === "HUMAN" && (
        <SupportCompensationPanel
          key={details.ticketId}
          ticketId={details.ticketId}
          handlingMode={details.handlingMode}
          onSubmitted={onCompensationSubmitted}
        />
      )}

      <div className="support-detail-sections">
        <DetailSection
          eyebrow="CUSTOMER VISIBLE"
          title="公开沟通"
          empty="暂无公开沟通"
          items={details.publicConversation.map((message, index) => (
            <li
              key={message.messageId ?? `${message.sentAt}-${index}`}
              className="conversation-entry"
            >
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
          sectionRef={factsRef}
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
  sectionRef,
}: {
  eyebrow: string;
  title: string;
  empty: string;
  items: ReactNode[];
  sectionRef?: React.RefObject<HTMLElement | null>;
}) {
  const id = `support-${title}`;
  return (
    <section
      ref={sectionRef}
      tabIndex={sectionRef ? -1 : undefined}
      className={`support-detail-section${sectionRef ? " context-entry-target" : ""}`}
      aria-labelledby={id}
    >
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
    !hasOnlyKeys(value, [
      "view",
      "schema",
      "cursor",
      "sharedQueue",
      "escalationQueue",
      "assignedTicketIds",
    ]) ||
    value.view !== "SUPPORT_WORKBENCH" ||
    value.schema !== SUPPORT_SCHEMA ||
    typeof value.cursor !== "string" ||
    parseCursor(value.cursor) === null ||
    !Array.isArray(value.sharedQueue) ||
    !Array.isArray(value.escalationQueue) ||
    !Array.isArray(value.assignedTicketIds) ||
    !value.assignedTicketIds.every((ticketId) => isTicketId(ticketId))
  )
    return false;
  return value.sharedQueue.every(isQueueItem) && value.escalationQueue.every(isQueueItem);
}

function isQueueItem(value: unknown): value is QueueItem {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "ticketId",
      "orderReference",
      "issueKind",
      "lifecycleState",
      "handlingMode",
      "enteredAt",
    ]) &&
    isTicketId(value.ticketId) &&
    typeof value.orderReference === "string" &&
    typeof value.issueKind === "string" &&
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
      "assignedSupportId",
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
    (value.assignedSupportId === undefined ||
      value.assignedSupportId === null ||
      typeof value.assignedSupportId === "string") &&
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
    hasOnlyKeys(value, ["messageId", "author", "body", "sentAt"]) &&
    (value.messageId === undefined || value.messageId === null || isTicketId(value.messageId)) &&
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
      "orderReference",
      "issueKind",
      "lifecycleState",
      "handlingMode",
      "sharedEnteredAt",
      "escalationEnteredAt",
    ]) &&
    isTicketId(value.ticketId) &&
    typeof value.orderReference === "string" &&
    typeof value.issueKind === "string" &&
    isLifecycleState(value.lifecycleState) &&
    isHandlingMode(value.handlingMode) &&
    typeof value.sharedEnteredAt === "string" &&
    (value.escalationEnteredAt === null || typeof value.escalationEnteredAt === "string")
  );
}

function isTicketId(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
}

function isSupportReplyResponse(value: unknown): value is SupportPublicReplyResponse {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "schema",
      "ticketId",
      "messageId",
      "publicMessageId",
      "outcome",
      "accepted",
      "replayed",
    ]) &&
    value.schema === SUPPORT_SCHEMA &&
    isTicketId(value.ticketId) &&
    typeof value.messageId === "string" &&
    value.messageId.trim().length > 0 &&
    isTicketId(value.publicMessageId) &&
    value.outcome === "ACCEPTED" &&
    value.accepted === true &&
    typeof value.replayed === "boolean"
  );
}

function createIdempotencyKey() {
  return globalThis.crypto.randomUUID();
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

function groupQueueItems(items: QueueItem[]) {
  const groups = new Map<string, QueueItem[]>();
  for (const item of items) {
    const group = groups.get(item.orderReference) ?? [];
    group.push(item);
    groups.set(item.orderReference, group);
  }
  return [...groups.entries()];
}

function issueKindLabel(issueKind: string) {
  return (
    {
      LOGISTICS_DELAY: "物流延迟",
      PACKAGE_NOT_RECEIVED: "包裹未收到",
      DUPLICATE_CHARGE: "重复扣款",
      ORDER_OPERATION_OR_RULE: "地址或取消规则",
      OTHER: "其他问题",
    }[issueKind] ?? "其他问题"
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
