import { FormEvent, useEffect, useRef, useState } from "react";
import { hasOnlyKeys, isRecord, parseSseEvent, parseViewCursor, type SseEvent } from "./streamProtocol";

const CUSTOMER_PUBLIC_SCHEMA = "customer-public-v1" as const;

type Snapshot = {
  view: "CUSTOMER_PUBLIC";
  schema: typeof CUSTOMER_PUBLIC_SCHEMA;
  cursor: string;
  ticket: { id: string; lifecycleState: string; handlingMode: string; agentGeneration: number; firstRespondedAt: string };
  messages: Array<{ author: string; body: string; sentAt: string }>;
  clarification: { id: string; promptCode: string; question: string } | null;
};

type EventEnvelope = {
  view: "CUSTOMER_PUBLIC";
  schema: typeof CUSTOMER_PUBLIC_SCHEMA;
  generation: number;
  payload: unknown;
};

const customerHeaders = { "X-Synthetic-Customer-Id": "customer-demo" };

export function App() {
  const [orderReference, setOrderReference] = useState("");
  const [description, setDescription] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [clarificationAnswer, setClarificationAnswer] = useState("");
  const [error, setError] = useState("");
  const requestId = useRef(globalThis.crypto.randomUUID());
  const replyMessageId = useRef(globalThis.crypto.randomUUID());
  const resumeRequestId = useRef(globalThis.crypto.randomUUID());
  const handoffRequestId = useRef(globalThis.crypto.randomUUID());
  const streamController = useRef<AbortController | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const snapshotRef = useRef<Snapshot | null>(null);

  useEffect(() => {
    const ticketId = new URLSearchParams(globalThis.location.search).get("ticket");
    if (ticketId && /^[0-9a-f-]{36}$/i.test(ticketId)) void loadTicket(ticketId);
    return () => {
      streamController.current?.abort();
      if (reconnectTimer.current !== null) globalThis.clearTimeout(reconnectTimer.current);
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const created = await fetch("/api/customer/tickets", {
        method: "POST",
        credentials: "same-origin",
        headers: { ...customerHeaders, "Content-Type": "application/json", "Idempotency-Key": requestId.current },
        body: JSON.stringify({ orderReference, description }),
      });
      if (!created.ok) throw new Error("ticket creation failed");
      const { ticketId } = await created.json() as { ticketId: string };
      await loadTicket(ticketId);
    } catch {
      setError("提交未完成，请保留本页并重试。相同请求不会创建第二张工单。");
    } finally {
      setSubmitting(false);
    }
  }

  async function loadTicket(ticketId: string) {
    const loaded = await fetch(`/api/customer/tickets/${ticketId}`, { headers: customerHeaders, credentials: "same-origin" });
    if (!loaded.ok) throw new Error("snapshot request failed");
    const authoritative = await loaded.json() as Snapshot;
    if (!isSnapshot(authoritative)) throw new Error("incompatible snapshot");
    snapshotRef.current = authoritative;
    setSnapshot(authoritative);
    setError("");
    globalThis.history.replaceState(null, "", `?ticket=${ticketId}`);
    void consumeEvents(ticketId, authoritative.cursor);
  }

  async function submitClarification(event: FormEvent) {
    event.preventDefault();
    if (!snapshot?.clarification) return;
    setSubmitting(true);
    setError("");
    const ticketId = snapshot.ticket.id;
    const clarificationId = snapshot.clarification.id;
    const headers = {
      ...customerHeaders,
      "Content-Type": "application/json",
      "Idempotency-Key": replyMessageId.current,
      "X-Resume-Request-Id": resumeRequestId.current,
    };
    try {
      const response = await fetch(`/api/customer/tickets/${ticketId}/clarifications/${clarificationId}/replies`, {
        method: "POST", credentials: "same-origin", headers,
        body: JSON.stringify({ answer: clarificationAnswer }),
      });
      if (!response.ok) throw new Error("clarification reply failed");
      await loadTicket(ticketId);
      replyMessageId.current = globalThis.crypto.randomUUID();
      resumeRequestId.current = globalThis.crypto.randomUUID();
      setClarificationAnswer("");
    } catch {
      const status = await fetch(`/api/customer/tickets/${ticketId}/clarification-resumes/${resumeRequestId.current}`, {
        headers: customerHeaders, credentials: "same-origin",
      }).catch(() => null);
      if (status?.ok) {
        await loadTicket(ticketId);
      } else {
        setError("回复状态暂时未知；请保留本页重试，稳定恢复身份不会启动第二次调查。");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function requestHumanHandoff() {
    if (!snapshot || snapshot.ticket.handlingMode === "HUMAN") return;
    setSubmitting(true);
    setError("");
    const ticketId = snapshot.ticket.id;
    const requestId = handoffRequestId.current;
    try {
      const response = await fetch(`/api/customer/tickets/${ticketId}/human-handoff`, {
        method: "POST",
        credentials: "same-origin",
        headers: { ...customerHeaders, "Content-Type": "application/json", "Idempotency-Key": requestId },
        body: JSON.stringify({ reasonCode: "CUSTOMER_REQUESTED" }),
      });
      if (!response.ok) throw new Error("human handoff failed");
      await loadTicket(ticketId);
      handoffRequestId.current = globalThis.crypto.randomUUID();
    } catch {
      const status = await fetch(`/api/customer/tickets/${ticketId}/human-handoff-requests/${requestId}`, {
        headers: customerHeaders,
        credentials: "same-origin",
      }).catch(() => null);
      if (status?.ok) {
        await loadTicket(ticketId);
        handoffRequestId.current = globalThis.crypto.randomUUID();
      } else {
        setError("转人工状态暂时未知；请保留本页重试，相同请求不会重复转人工。");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function consumeEvents(ticketId: string, cursor: string) {
    streamController.current?.abort();
    const controller = new AbortController();
    streamController.current = controller;
    const markDisconnected = () => {
      if (!controller.signal.aborted) setError("实时更新已断开；当前内容可能过期，刷新后将从权威快照恢复。");
    };
    const scheduleRecovery = () => {
      if (controller.signal.aborted || streamController.current !== controller || reconnectTimer.current !== null) return;
      reconnectTimer.current = globalThis.setTimeout(async () => {
        reconnectTimer.current = null;
        if (streamController.current !== controller) return;
        try {
          await loadTicket(ticketId);
        } catch {
          markDisconnected();
          scheduleRecovery();
        }
      }, 1_000);
    };
    try {
      const response = await fetch(`/api/customer/tickets/${ticketId}/events`, {
        headers: { ...customerHeaders, "Last-Event-ID": cursor, Accept: "text/event-stream" },
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("event stream failed");
      const reader = response.body?.getReader();
      if (reader) {
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
            const event = parseSseEvent(block);
            if (event && !applyPublicEvent(event)) {
              controller.abort();
              await loadTicket(ticketId);
              return;
            }
            boundary = buffer.search(/\r?\n\r?\n/);
          }
          if (done) break;
        }
      }
    } catch {
      // The authoritative snapshot remains committed and readable after a stream failure.
    }
    markDisconnected();
    scheduleRecovery();
  }

  function applyPublicEvent(event: SseEvent) {
    const current = snapshotRef.current;
    if (!current) return true;
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
    if (!isRecord(envelope) || !hasOnlyKeys(envelope, ["view", "schema", "generation", "payload"])
      || envelope.view !== "CUSTOMER_PUBLIC" || envelope.schema !== CUSTOMER_PUBLIC_SCHEMA
      || !Number.isSafeInteger(envelope.generation) || envelope.generation < 0) return false;
    if (envelope.generation < current.ticket.agentGeneration) {
      const next = { ...current, cursor: event.id };
      snapshotRef.current = next;
      setSnapshot(next);
      return true;
    }
    if (envelope.generation > current.ticket.agentGeneration) return false;
    const payload = envelope.payload;
    let next: Snapshot;
    if (event.type === "PUBLIC_MESSAGE_APPENDED") {
      if (!isPublicMessage(payload)) return false;
      const message = payload;
      if (current.ticket.handlingMode === "HUMAN" && message.author === "AGENT") {
        next = { ...current, cursor: event.id };
      } else {
        const duplicate = current.messages.some((existing) =>
          existing.author === message.author && existing.body === message.body && existing.sentAt === message.sentAt);
        next = { ...current, cursor: event.id, messages: duplicate ? current.messages : [...current.messages, message] };
      }
    } else if (event.type === "TICKET_ACCEPTED") {
      if (!isTicketTransition(payload)) return false;
      next = { ...current, cursor: event.id, ticket: { ...current.ticket, ...payload } };
    } else if (event.type === "CUSTOMER_CLARIFICATION_REQUESTED" || event.type === "TICKET_INVESTIGATION_RESUMED") {
      if (!isClarificationTransition(payload)) return false;
      next = {
          ...current,
          cursor: event.id,
          ticket: { ...current.ticket, lifecycleState: payload.lifecycleState },
          clarification: payload.clarification === undefined ? current.clarification : payload.clarification,
        };
    } else if (event.type === "TICKET_HANDED_OFF") {
      if (!isHandoffTransition(payload)) return false;
      next = {
          ...current,
          cursor: event.id,
          ticket: { ...current.ticket, handlingMode: payload.handlingMode },
          clarification: null,
        };
    } else if (event.type === "TICKET_RESOLVED") {
      if (!isResolvedTransition(payload)) return false;
      next = { ...current, cursor: event.id, ticket: { ...current.ticket, lifecycleState: payload.lifecycleState } };
    } else {
      return false;
    }
    snapshotRef.current = next;
    setSnapshot(next);
    return true;
  }

  return (
    <main className="help-center">
      <header>
        <p className="eyebrow">STELLOGIC 帮助中心</p>
        <h1>物流遇到问题？<br />我们从这里开始处理。</h1>
        <p className="lede">提交后，你会得到一张可查询的客服工单。调查异步继续；订单无法唯一确认时，我们会在同一工单中向你提问。</p>
      </header>

      {!snapshot ? (
        <form className="ticket-form" onSubmit={submit}>
          <label>订单编号<input aria-label="订单编号" value={orderReference} onChange={(event) => setOrderReference(event.target.value)} required /></label>
          <label>问题描述<textarea aria-label="问题描述" value={description} onChange={(event) => setDescription(event.target.value)} required rows={5} /></label>
          <button disabled={submitting}>{submitting ? "正在提交…" : "提交物流延迟问题"}</button>
          {error && <p className="error" role="alert">{error}</p>}
        </form>
      ) : (
        <section className="ticket-card" aria-live="polite">
          <div className="ticket-heading">
            <div><p className="eyebrow">客服工单</p><h2>{snapshot.ticket.id}</h2></div>
            <span className="status">{snapshot.ticket.handlingMode === "HUMAN" ? "人工处理中" : snapshot.ticket.lifecycleState === "INVESTIGATING" ? "调查中" : snapshot.ticket.lifecycleState === "WAITING_FOR_CUSTOMER" ? "等待你的回复" : snapshot.ticket.lifecycleState}</span>
          </div>
          <ol className="conversation">
            {snapshot.messages.map((message, index) => (
              <li key={`${message.sentAt}-${index}`} className={message.author.toLowerCase()}>
                <span>{message.author === "CUSTOMER" ? "你" : message.author === "AGENT" ? "智能客服" : "客服"}</span>
                <p>{message.body}</p>
              </li>
            ))}
          </ol>
          {snapshot.clarification && snapshot.ticket.handlingMode === "AGENT" && (
            <form className="clarification-form" onSubmit={submitClarification}>
              <label>{snapshot.clarification.question}
                <input aria-label="订单确认码" value={clarificationAnswer}
                  onChange={(event) => setClarificationAnswer(event.target.value)} required />
              </label>
              <button disabled={submitting}>{submitting ? "正在恢复调查…" : "回复并继续调查"}</button>
            </form>
          )}
          {snapshot.ticket.handlingMode === "AGENT" && snapshot.ticket.lifecycleState !== "CLOSED" && (
            <button type="button" className="handoff-button" disabled={submitting} onClick={requestHumanHandoff}>
              {submitting ? "正在提交…" : "转人工处理"}
            </button>
          )}
          <p className="recovery-note">刷新页面时，公开沟通会从 Spring 权威快照恢复。</p>
          {error && <p className="error" role="alert">{error}</p>}
        </section>
      )}
    </main>
  );
}

function isSnapshot(value: unknown): value is Snapshot {
  if (!isRecord(value) || value.view !== "CUSTOMER_PUBLIC" || value.schema !== CUSTOMER_PUBLIC_SCHEMA) return false;
  const cursor = typeof value.cursor === "string" ? parseCursor(value.cursor) : null;
  return cursor?.epoch === value.schema && isRecord(value.ticket) && Array.isArray(value.messages)
    && Number.isSafeInteger(value.ticket.agentGeneration) && Number(value.ticket.agentGeneration) >= 0
    && value.messages.every(isPublicMessage);
}

function parseCursor(cursor: string) {
  return parseViewCursor(cursor, CUSTOMER_PUBLIC_SCHEMA);
}

function isPublicMessage(value: unknown): value is Snapshot["messages"][number] {
  return isRecord(value) && hasOnlyKeys(value, ["author", "body", "sentAt"])
    && ["CUSTOMER", "SUPPORT", "AGENT"].includes(String(value.author))
    && typeof value.body === "string" && typeof value.sentAt === "string";
}

function isTicketTransition(value: unknown): value is { lifecycleState: string; handlingMode: string; ticketId?: string } {
  return isRecord(value) && hasOnlyKeys(value, ["ticketId", "lifecycleState", "handlingMode"])
    && typeof value.lifecycleState === "string" && typeof value.handlingMode === "string";
}

function isClarificationTransition(value: unknown): value is { lifecycleState: string; clarification?: Snapshot["clarification"] } {
  if (!isRecord(value) || !hasOnlyKeys(value, ["lifecycleState", "clarification"]) || typeof value.lifecycleState !== "string") return false;
  const clarification = value.clarification;
  return clarification === undefined || clarification === null
    || (isRecord(clarification) && hasOnlyKeys(clarification, ["id", "promptCode", "question"])
      && typeof clarification.id === "string" && typeof clarification.promptCode === "string"
      && typeof clarification.question === "string");
}

function isHandoffTransition(value: unknown): value is { handlingMode: string; clarification: null } {
  return isRecord(value) && hasOnlyKeys(value, ["handlingMode", "clarification"])
    && value.handlingMode === "HUMAN" && value.clarification === null;
}

function isResolvedTransition(value: unknown): value is { lifecycleState: string } {
  return isRecord(value) && hasOnlyKeys(value, ["lifecycleState"]) && value.lifecycleState === "RESOLVED";
}
