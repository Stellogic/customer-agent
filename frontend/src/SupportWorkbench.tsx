import { useEffect, useRef, useState } from "react";

const SUPPORT_SCHEMA = "support-workbench-v1" as const;
const lifecycleStates = ["NEW", "INVESTIGATING", "WAITING_FOR_CUSTOMER", "WAITING_FOR_EXTERNAL", "RESOLVED", "CLOSED"] as const;
const handlingModes = ["AGENT", "HUMAN"] as const;
type LifecycleState = typeof lifecycleStates[number];
type HandlingMode = typeof handlingModes[number];

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

type StreamEvent = { id: string; type: string; data: string };
type EventEnvelope = {
  view: "SUPPORT_WORKBENCH";
  schema: typeof SUPPORT_SCHEMA;
  payload: unknown;
};
type QueueUpsert = QueueItem & { sharedEnteredAt: string; escalationEnteredAt: string | null };

export function SupportWorkbench({ supportId }: { supportId: string }) {
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [connection, setConnection] = useState<"loading" | "syncing" | "resetting" | "live" | "stale">("loading");
  const snapshotRef = useRef<WorkbenchSnapshot | null>(null);
  const streamController = useRef<AbortController | null>(null);
  const supportHeaders = { "X-Synthetic-Support-Id": supportId };

  useEffect(() => {
    void loadSnapshot("loading");
    return () => streamController.current?.abort();
  }, []);

  async function loadSnapshot(status: "loading" | "syncing" | "resetting" = "syncing") {
    streamController.current?.abort();
    setConnection(status);
    try {
      const response = await fetch("/api/support/workbench/snapshot", {
        headers: supportHeaders,
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error("snapshot request failed");
      const authoritative = await response.json() as unknown;
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
      const response = await fetch("/api/support/workbench/events", {
        headers: { ...supportHeaders, "Last-Event-ID": cursor, Accept: "text/event-stream" },
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      });
      if (response.status === 409) {
        await recoverFromSnapshot(controller);
        return;
      }
      if (!response.ok) throw new Error("event stream failed");
      const reader = response.body?.getReader();
      if (!reader) throw new Error("event stream body missing");
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        let boundary = buffer.search(/\r?\n\r?\n/);
        while (boundary >= 0) {
          const block = buffer.slice(0, boundary);
          const separator = buffer.slice(boundary).match(/^\r?\n\r?\n/)?.[0].length ?? 2;
          buffer = buffer.slice(boundary + separator);
          const event = parseEvent(block);
          if (event && !applyEvent(event)) {
            await recoverFromSnapshot(controller);
            return;
          }
          boundary = buffer.search(/\r?\n\r?\n/);
        }
        if (done) break;
      }
    } catch {
      // The last snapshot stays visible but is explicitly marked stale.
    }
    if (!controller.signal.aborted && streamController.current === controller) setConnection("stale");
  }

  async function recoverFromSnapshot(controller: AbortController) {
    if (streamController.current !== controller) return;
    controller.abort();
    setConnection("resetting");
    await new Promise<void>((resolve) => globalThis.setTimeout(resolve, 0));
    await loadSnapshot("resetting");
  }

  function applyEvent(event: StreamEvent) {
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
    if (!isRecord(envelope) || !hasOnlyKeys(envelope, ["view", "schema", "payload"])
      || envelope.view !== "SUPPORT_WORKBENCH" || envelope.schema !== SUPPORT_SCHEMA) return false;

    let next: WorkbenchSnapshot;
    if (event.type === "QUEUE_TICKET_REMOVED") {
      if (!isRemoval(envelope.payload)) return false;
      const payload = envelope.payload;
      next = {
        ...current,
        cursor: event.id,
        sharedQueue: current.sharedQueue.filter((item) => item.ticketId !== payload.ticketId),
        escalationQueue: current.escalationQueue.filter((item) => item.ticketId !== payload.ticketId),
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
        escalationQueue: envelope.payload.escalationEnteredAt === null
          ? current.escalationQueue.filter((entry) => entry.ticketId !== item.ticketId)
          : upsertAndSort(current.escalationQueue, { ...item, enteredAt: envelope.payload.escalationEnteredAt }),
      };
    } else {
      return false;
    }
    snapshotRef.current = next;
    setSnapshot(next);
    return true;
  }

  return (
    <main className="support-workbench" aria-label="客服工作台">
      <header className="workbench-header">
        <div>
          <p className="eyebrow">SUPPORT WORKBENCH</p>
          <h1>客服共享队列</h1>
          <p className="lede">发现需要人工关注的客服工单；领取与完整人工处理不在当前切片中。</p>
        </div>
        <div className={`connection-state ${connection}`} role={connection === "stale" || connection === "resetting" ? "alert" : "status"} aria-live="polite">
          {connection === "loading" && "正在读取权威快照…"}
          {connection === "syncing" && "正在从 Spring 权威快照重新同步…"}
          {connection === "resetting" && "事件流已失效；当前队列可能过期，正在重新读取权威快照…"}
          {connection === "live" && "队列已与 Spring 权威状态同步"}
          {connection === "stale" && "实时连接已断开；当前队列可能过期。"}
        </div>
      </header>

      <p className="authorization-note">队列可发现不等于工单详情授权</p>

      <div className="queue-grid" aria-busy={connection === "loading" || connection === "syncing" || connection === "resetting"}>
        <QueueSection
          title="待接手工单"
          description="转人工与其他共享队列条目"
          items={snapshot?.sharedQueue ?? []}
        />
        <QueueSection
          title="SLA 违约升级"
          description="已发生 SLA 违约、需要提高关注的工单"
          items={snapshot?.escalationQueue ?? []}
          accent
        />
      </div>

      <footer className="workbench-footer">
        <p>快照游标与客户、审批视图相互独立；刷新不会沿用旧本地队列。</p>
        <button type="button" onClick={() => void loadSnapshot()} disabled={connection === "loading" || connection === "syncing" || connection === "resetting"}>
          重新同步队列
        </button>
      </footer>
    </main>
  );
}

function QueueSection({ title, description, items, accent = false }: {
  title: string;
  description: string;
  items: QueueItem[];
  accent?: boolean;
}) {
  return (
    <section className={`queue-panel${accent ? " escalation" : ""}`} aria-labelledby={`${title}-title`}>
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
                <span>{stateLabel(item.lifecycleState)} · {item.handlingMode === "HUMAN" ? "人工处理" : "Agent 处理"}</span>
              </div>
              <time dateTime={item.enteredAt}>{formatTime(item.enteredAt)}</time>
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
  if (!isRecord(value) || !hasOnlyKeys(value, ["view", "schema", "cursor", "sharedQueue", "escalationQueue"])
    || value.view !== "SUPPORT_WORKBENCH" || value.schema !== SUPPORT_SCHEMA
    || typeof value.cursor !== "string" || parseCursor(value.cursor) === null
    || !Array.isArray(value.sharedQueue) || !Array.isArray(value.escalationQueue)) return false;
  return value.sharedQueue.every(isQueueItem) && value.escalationQueue.every(isQueueItem);
}

function isQueueItem(value: unknown): value is QueueItem {
  return isRecord(value) && hasOnlyKeys(value, ["ticketId", "lifecycleState", "handlingMode", "enteredAt"])
    && isTicketId(value.ticketId) && isLifecycleState(value.lifecycleState) && isHandlingMode(value.handlingMode)
    && typeof value.enteredAt === "string";
}

function isRemoval(value: unknown): value is { ticketId: string } {
  return isRecord(value) && hasOnlyKeys(value, ["ticketId"])
    && isTicketId(value.ticketId);
}

function isUpsert(value: unknown): value is QueueUpsert {
  return isRecord(value)
    && hasOnlyKeys(value, ["ticketId", "lifecycleState", "handlingMode", "sharedEnteredAt", "escalationEnteredAt"])
    && isTicketId(value.ticketId) && isLifecycleState(value.lifecycleState) && isHandlingMode(value.handlingMode)
    && typeof value.sharedEnteredAt === "string"
    && (value.escalationEnteredAt === null || typeof value.escalationEnteredAt === "string");
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
  const separator = cursor.lastIndexOf(":");
  if (separator < 1 || cursor.slice(0, separator) !== SUPPORT_SCHEMA) return null;
  const sequence = cursor.slice(separator + 1);
  return /^(0|[1-9]\d*)$/.test(sequence) && Number.isSafeInteger(Number(sequence))
    ? { epoch: SUPPORT_SCHEMA, sequence: Number(sequence) }
    : null;
}

function parseEvent(block: string): StreamEvent | null {
  let id = "";
  let type = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("id:")) id = line.slice(3).trimStart();
    else if (line.startsWith("event:")) type = line.slice(6).trimStart();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return id && data.length ? { id, type, data: data.join("\n") } : null;
}

function upsertAndSort(items: QueueItem[], item: QueueItem) {
  return [...items.filter((existing) => existing.ticketId !== item.ticketId), item]
    .sort((left, right) => left.enteredAt.localeCompare(right.enteredAt) || left.ticketId.localeCompare(right.ticketId));
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
  return Number.isNaN(instant.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(instant);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, keys: string[]) {
  return Object.keys(value).every((key) => keys.includes(key));
}
