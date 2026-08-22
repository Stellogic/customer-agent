import { FormEvent, useEffect, useRef, useState } from "react";
import {
  consumeSseEvents,
  hasOnlyKeys,
  isRecord,
  parseViewCursor,
  type SseEvent,
} from "./streamProtocol";
import { loadCsrfToken } from "./csrf";

const CUSTOMER_PUBLIC_SCHEMA = "customer-public-v1" as const;

type Snapshot = {
  view: "CUSTOMER_PUBLIC";
  schema: typeof CUSTOMER_PUBLIC_SCHEMA;
  cursor: string;
  ticket: {
    id: string;
    lifecycleState: string;
    handlingMode: string;
    agentGeneration: number;
    firstRespondedAt: string;
  };
  messages: Array<{ author: string; body: string; sentAt: string }>;
  clarification: { id: string; promptCode: string; question: string } | null;
};

type EventEnvelope = {
  view: "CUSTOMER_PUBLIC";
  schema: typeof CUSTOMER_PUBLIC_SCHEMA;
  generation: number;
  payload: unknown;
};

function clarificationRejectionMessage(status: number) {
  switch (status) {
    case 401:
      return "登录状态已失效，请重新登录后再试。";
    case 403:
      return "你当前无权回复这张工单。";
    case 404:
      return "未找到该工单或澄清请求，请返回工单列表确认。";
    default:
      return null;
  }
}

export function App() {
  const [orderReference, setOrderReference] = useState("");
  const [description, setDescription] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [clarificationAnswer, setClarificationAnswer] = useState("");
  const [ticketReplyOrderReference, setTicketReplyOrderReference] = useState("");
  const [ticketReplyIssueKind, setTicketReplyIssueKind] = useState("LOGISTICS_DELAY");
  const [ticketReplyBody, setTicketReplyBody] = useState("");
  const [error, setError] = useState("");
  const requestId = useRef(globalThis.crypto.randomUUID());
  const replyMessageId = useRef(globalThis.crypto.randomUUID());
  const resumeRequestId = useRef(globalThis.crypto.randomUUID());
  const handoffRequestId = useRef(globalThis.crypto.randomUUID());
  const ticketReplyRequestId = useRef(globalThis.crypto.randomUUID());
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
      const csrf = await loadCsrfToken();
      const created = await fetch("/api/customer/tickets", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          [csrf.headerName]: csrf.token,
          "Content-Type": "application/json",
          "Idempotency-Key": requestId.current,
        },
        body: JSON.stringify({ orderReference, description }),
      });
      if (!created.ok) throw new Error("ticket creation failed");
      const { ticketId } = (await created.json()) as { ticketId: string };
      await loadTicket(ticketId);
    } catch {
      setError("提交未完成，请保留本页并重试。相同请求不会创建第二张工单。");
    } finally {
      setSubmitting(false);
    }
  }

  async function loadTicket(ticketId: string) {
    const loaded = await fetch(`/api/customer/tickets/${ticketId}`, {
      credentials: "same-origin",
    });
    if (!loaded.ok) throw new Error("snapshot request failed");
    const authoritative = (await loaded.json()) as Snapshot;
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
    try {
      const csrf = await loadCsrfToken();
      const headers = {
        [csrf.headerName]: csrf.token,
        "Content-Type": "application/json",
        "Idempotency-Key": replyMessageId.current,
        "X-Resume-Request-Id": resumeRequestId.current,
      };
      const response = await fetch(
        `/api/customer/tickets/${ticketId}/clarifications/${clarificationId}/replies`,
        {
          method: "POST",
          credentials: "same-origin",
          headers,
          body: JSON.stringify({ answer: clarificationAnswer }),
        },
      );
      if (response.status === 422) {
        rotateClarificationRequestIds();
        setError("回复内容未通过校验，请检查后重新提交。");
        return;
      }
      if (response.status === 409) {
        rotateClarificationRequestIds();
        try {
          await loadTicket(ticketId);
          setError("该澄清已失效或工单状态已变化，已刷新最新状态。");
        } catch {
          setError("该澄清已失效或工单状态已变化；最新状态刷新失败，请手动刷新。");
        }
        return;
      }
      const deterministicError = clarificationRejectionMessage(response.status);
      if (deterministicError) {
        rotateClarificationRequestIds();
        setError(deterministicError);
        return;
      }
      if (!response.ok && response.status < 500) {
        rotateClarificationRequestIds();
        setError("回复未被接受，请检查当前工单状态后重试。");
        return;
      }
      if (!response.ok) throw new Error("clarification reply result unknown");
      rotateClarificationRequestIds();
      setClarificationAnswer("");
      try {
        await loadTicket(ticketId);
      } catch {
        setError("回复已提交，但最新工单状态刷新失败，请手动刷新。");
      }
    } catch {
      const status = await fetch(
        `/api/customer/tickets/${ticketId}/clarification-resumes/${resumeRequestId.current}`,
        {
          credentials: "same-origin",
        },
      ).catch(() => null);
      if (status?.ok) {
        try {
          await loadTicket(ticketId);
          if (snapshotRef.current?.clarification?.id !== clarificationId) {
            rotateClarificationRequestIds();
            setClarificationAnswer("");
          }
        } catch {
          setError("已找到原回复的恢复记录，但最新工单状态刷新失败，请手动刷新。");
        }
      } else {
        setError("回复状态暂时未知；请保留本页重试，稳定恢复身份不会启动第二次调查。");
      }
    } finally {
      setSubmitting(false);
    }

    function rotateClarificationRequestIds() {
      replyMessageId.current = globalThis.crypto.randomUUID();
      resumeRequestId.current = globalThis.crypto.randomUUID();
    }
  }

  async function requestHumanHandoff() {
    if (!snapshot || snapshot.ticket.handlingMode === "HUMAN") return;
    setSubmitting(true);
    setError("");
    const ticketId = snapshot.ticket.id;
    const requestId = handoffRequestId.current;
    try {
      const csrf = await loadCsrfToken();
      const response = await fetch(`/api/customer/tickets/${ticketId}/human-handoff`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          [csrf.headerName]: csrf.token,
          "Content-Type": "application/json",
          "Idempotency-Key": requestId,
        },
        body: JSON.stringify({ reasonCode: "CUSTOMER_REQUESTED" }),
      });
      if (!response.ok) throw new Error("human handoff failed");
      await loadTicket(ticketId);
      handoffRequestId.current = globalThis.crypto.randomUUID();
    } catch {
      const status = await fetch(
        `/api/customer/tickets/${ticketId}/human-handoff-requests/${requestId}`,
        {
          credentials: "same-origin",
        },
      ).catch(() => null);
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

  async function submitTicketReply(event: FormEvent) {
    event.preventDefault();
    if (!snapshot || !["RESOLVED", "CLOSED"].includes(snapshot.ticket.lifecycleState)) return;
    setSubmitting(true);
    setError("");
    try {
      const csrf = await loadCsrfToken();
      const response = await fetch(`/api/customer/tickets/${snapshot.ticket.id}/replies`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          [csrf.headerName]: csrf.token,
          "Content-Type": "application/json",
          "Idempotency-Key": ticketReplyRequestId.current,
        },
        body: JSON.stringify({
          orderReference: ticketReplyOrderReference,
          issueKind: ticketReplyIssueKind,
          message: ticketReplyBody,
        }),
      });
      if (!response.ok) throw new Error("ticket reply failed");
      const result = (await response.json()) as { ticketId: string };
      await loadTicket(result.ticketId);
      ticketReplyRequestId.current = globalThis.crypto.randomUUID();
      setTicketReplyBody("");
    } catch {
      setError("回复状态暂时未知；请保留本页重试，相同消息身份不会重开或创建第二张工单。");
    } finally {
      setSubmitting(false);
    }
  }

  async function consumeEvents(ticketId: string, cursor: string) {
    streamController.current?.abort();
    const controller = new AbortController();
    streamController.current = controller;
    const markDisconnected = () => {
      if (!controller.signal.aborted)
        setError("实时更新已断开；当前内容可能过期，刷新后将从权威快照恢复。");
    };
    const scheduleRecovery = () => {
      if (
        controller.signal.aborted ||
        streamController.current !== controller ||
        reconnectTimer.current !== null
      )
        return;
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
        headers: { "Last-Event-ID": cursor, Accept: "text/event-stream" },
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("event stream failed");
      const compatible = await consumeSseEvents(response.body, applyPublicEvent);
      if (!compatible) {
        controller.abort();
        await loadTicket(ticketId);
        return;
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
    if (
      !isRecord(envelope) ||
      !hasOnlyKeys(envelope, ["view", "schema", "generation", "payload"]) ||
      envelope.view !== "CUSTOMER_PUBLIC" ||
      envelope.schema !== CUSTOMER_PUBLIC_SCHEMA ||
      !Number.isSafeInteger(envelope.generation) ||
      envelope.generation < 0
    )
      return false;
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
        const duplicate = current.messages.some(
          (existing) =>
            existing.author === message.author &&
            existing.body === message.body &&
            existing.sentAt === message.sentAt,
        );
        next = {
          ...current,
          cursor: event.id,
          messages: duplicate ? current.messages : [...current.messages, message],
        };
      }
    } else if (event.type === "TICKET_ACCEPTED") {
      if (!isTicketTransition(payload)) return false;
      next = { ...current, cursor: event.id, ticket: { ...current.ticket, ...payload } };
    } else if (
      event.type === "CUSTOMER_CLARIFICATION_REQUESTED" ||
      event.type === "TICKET_INVESTIGATION_RESUMED"
    ) {
      if (!isClarificationTransition(payload)) return false;
      next = {
        ...current,
        cursor: event.id,
        ticket: { ...current.ticket, lifecycleState: payload.lifecycleState },
        clarification:
          payload.clarification === undefined ? current.clarification : payload.clarification,
      };
    } else if (event.type === "TICKET_HANDED_OFF") {
      if (!isHandoffTransition(payload)) return false;
      next = {
        ...current,
        cursor: event.id,
        ticket: { ...current.ticket, handlingMode: payload.handlingMode },
        clarification: null,
      };
    } else if (
      event.type === "TICKET_RESOLVED" ||
      event.type === "TICKET_REOPENED" ||
      event.type === "TICKET_CLOSED"
    ) {
      if (!isLifecycleTransition(payload, event.type)) return false;
      next = {
        ...current,
        cursor: event.id,
        ticket: { ...current.ticket, lifecycleState: payload.lifecycleState },
      };
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
        <h1>
          物流遇到问题？
          <br />
          我们从这里开始处理。
        </h1>
        <p className="lede">
          提交后，你会得到一张可查询的客服工单。调查异步继续；订单无法唯一确认时，我们会在同一工单中向你提问。
        </p>
      </header>

      {!snapshot ? (
        <form className="ticket-form" onSubmit={submit}>
          <label>
            订单编号
            <input
              aria-label="订单编号"
              value={orderReference}
              onChange={(event) => setOrderReference(event.target.value)}
              required
            />
          </label>
          <label>
            问题描述
            <textarea
              aria-label="问题描述"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              required
              rows={5}
            />
          </label>
          <button disabled={submitting}>{submitting ? "正在提交…" : "提交物流延迟问题"}</button>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </form>
      ) : (
        <section className="ticket-card" aria-live="polite">
          <div className="ticket-heading">
            <div>
              <p className="eyebrow">客服工单</p>
              <h2>{snapshot.ticket.id}</h2>
            </div>
            <span className="status">
              {snapshot.ticket.lifecycleState === "CLOSED"
                ? "已关闭"
                : snapshot.ticket.handlingMode === "HUMAN"
                  ? "人工处理中"
                  : snapshot.ticket.lifecycleState === "INVESTIGATING"
                    ? "调查中"
                    : snapshot.ticket.lifecycleState === "WAITING_FOR_CUSTOMER"
                      ? "等待你的回复"
                      : snapshot.ticket.lifecycleState}
            </span>
          </div>
          <ol className="conversation">
            {snapshot.messages.map((message, index) => (
              <li key={`${message.sentAt}-${index}`} className={message.author.toLowerCase()}>
                <span>
                  {message.author === "CUSTOMER"
                    ? "你"
                    : message.author === "AGENT"
                      ? "智能客服"
                      : "客服"}
                </span>
                <p>{message.body}</p>
              </li>
            ))}
          </ol>
          {snapshot.clarification && snapshot.ticket.handlingMode === "AGENT" && (
            <form className="clarification-form" onSubmit={submitClarification}>
              <label>
                {snapshot.clarification.question}
                <input
                  aria-label="订单确认码"
                  value={clarificationAnswer}
                  onChange={(event) => setClarificationAnswer(event.target.value)}
                  required
                />
              </label>
              <button disabled={submitting}>
                {submitting ? "正在恢复调查…" : "回复并继续调查"}
              </button>
            </form>
          )}
          {["RESOLVED", "CLOSED"].includes(snapshot.ticket.lifecycleState) && (
            <form className="clarification-form" onSubmit={submitTicketReply}>
              <label>
                回复涉及的订单编号
                <input
                  aria-label="回复订单编号"
                  value={ticketReplyOrderReference}
                  onChange={(event) => setTicketReplyOrderReference(event.target.value)}
                  required
                />
              </label>
              <label>
                这是哪类问题
                <select
                  aria-label="回复问题类型"
                  value={ticketReplyIssueKind}
                  onChange={(event) => setTicketReplyIssueKind(event.target.value)}
                >
                  <option value="LOGISTICS_DELAY">原物流延迟问题</option>
                  <option value="OTHER">其他问题</option>
                </select>
              </label>
              <label>
                你的回复
                <textarea
                  aria-label="工单回复"
                  value={ticketReplyBody}
                  onChange={(event) => setTicketReplyBody(event.target.value)}
                  required
                  rows={3}
                />
              </label>
              <button disabled={submitting}>{submitting ? "正在提交…" : "发送回复"}</button>
            </form>
          )}
          {snapshot.ticket.handlingMode === "AGENT" &&
            snapshot.ticket.lifecycleState !== "CLOSED" && (
              <button
                type="button"
                className="handoff-button"
                disabled={submitting}
                onClick={requestHumanHandoff}
              >
                {submitting ? "正在提交…" : "转人工处理"}
              </button>
            )}
          <p className="recovery-note">刷新页面时，公开沟通会从 Spring 权威快照恢复。</p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </section>
      )}
    </main>
  );
}

function isSnapshot(value: unknown): value is Snapshot {
  if (
    !isRecord(value) ||
    value.view !== "CUSTOMER_PUBLIC" ||
    value.schema !== CUSTOMER_PUBLIC_SCHEMA
  )
    return false;
  const cursor = typeof value.cursor === "string" ? parseCursor(value.cursor) : null;
  return (
    cursor?.epoch === value.schema &&
    isRecord(value.ticket) &&
    Array.isArray(value.messages) &&
    Number.isSafeInteger(value.ticket.agentGeneration) &&
    Number(value.ticket.agentGeneration) >= 0 &&
    value.messages.every(isPublicMessage)
  );
}

function parseCursor(cursor: string) {
  return parseViewCursor(cursor, CUSTOMER_PUBLIC_SCHEMA);
}

function isPublicMessage(value: unknown): value is Snapshot["messages"][number] {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["author", "body", "sentAt"]) &&
    ["CUSTOMER", "SUPPORT", "AGENT"].includes(String(value.author)) &&
    typeof value.body === "string" &&
    typeof value.sentAt === "string"
  );
}

function isTicketTransition(
  value: unknown,
): value is { lifecycleState: string; handlingMode: string; ticketId?: string } {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["ticketId", "lifecycleState", "handlingMode"]) &&
    typeof value.lifecycleState === "string" &&
    typeof value.handlingMode === "string"
  );
}

function isClarificationTransition(
  value: unknown,
): value is { lifecycleState: string; clarification?: Snapshot["clarification"] } {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ["lifecycleState", "clarification"]) ||
    typeof value.lifecycleState !== "string"
  )
    return false;
  const clarification = value.clarification;
  return (
    clarification === undefined ||
    clarification === null ||
    (isRecord(clarification) &&
      hasOnlyKeys(clarification, ["id", "promptCode", "question"]) &&
      typeof clarification.id === "string" &&
      typeof clarification.promptCode === "string" &&
      typeof clarification.question === "string")
  );
}

function isHandoffTransition(
  value: unknown,
): value is { handlingMode: string; clarification: null } {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["handlingMode", "clarification"]) &&
    value.handlingMode === "HUMAN" &&
    value.clarification === null
  );
}

function isLifecycleTransition(
  value: unknown,
  eventType: string,
): value is { lifecycleState: string } {
  if (!isRecord(value) || !hasOnlyKeys(value, ["lifecycleState"])) return false;
  const expected =
    eventType === "TICKET_RESOLVED"
      ? "RESOLVED"
      : eventType === "TICKET_REOPENED"
        ? "INVESTIGATING"
        : "CLOSED";
  return value.lifecycleState === expected;
}
