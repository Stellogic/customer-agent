import { FormEvent, useEffect, useRef, useState } from "react";
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

const PUBLIC_CONVERSATION_SCHEMA = "public-conversation-v2" as const;
const PUBLIC_CONVERSATION_BASE = "/api/customer/v2/tickets";
const CUSTOMER_INTAKE_SCHEMA = "customer-intake-v2" as const;
const CUSTOMER_INTAKE_BASE = "/api/customer/v2/intakes";

type Snapshot = {
  view: "PUBLIC_CONVERSATION";
  schema: typeof PUBLIC_CONVERSATION_SCHEMA;
  cursor: string;
  ticket: {
    id: string;
    lifecycleState: string;
    handlingMode: string;
    agentGeneration: number;
  };
  messages: Array<{ author: string; body: string; sentAt: string }>;
  clarification: { id: string; promptCode: string; question: string } | null;
};

type EventEnvelope = {
  view: "PUBLIC_CONVERSATION";
  schema: typeof PUBLIC_CONVERSATION_SCHEMA;
  generation: number;
  payload: unknown;
};

type IntakeSnapshot = {
  schema: "customer-intake-v1" | typeof CUSTOMER_INTAKE_SCHEMA;
  intakeId: string;
  status: "READY_TO_CONFIRM" | "NEEDS_CLARIFICATION" | "CONFIRMED";
  candidateOrder: { reference: string; summary: string } | null;
  issue: IntakeIssue | null;
  issues: IntakeIssue[];
  assistantMessage: string;
  ticketId: string | null;
  ticketIds: string[];
  sharedIntakeRecordId: string | null;
  expectedTicketCount: number;
  confirmed: boolean;
  replayed: boolean;
};

type IntakeIssue = {
  kind: "LOGISTICS_DELAY" | "PACKAGE_NOT_RECEIVED" | "DUPLICATE_CHARGE";
  summary: string;
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
  const [intake, setIntake] = useState<IntakeSnapshot | null>(null);
  const [intakeReply, setIntakeReply] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [clarificationAnswer, setClarificationAnswer] = useState("");
  const [ticketReplyOrderReference, setTicketReplyOrderReference] = useState("");
  const [ticketReplyIssueKind, setTicketReplyIssueKind] = useState("LOGISTICS_DELAY");
  const [ticketReplyBody, setTicketReplyBody] = useState("");
  const [error, setError] = useState("");
  const [copiedTicketId, setCopiedTicketId] = useState(false);
  const [confirmingHumanHandoff, setConfirmingHumanHandoff] = useState(false);
  const [initialTicketId] = useState(readRequestedTicketId);
  const [unknownHandoffRequestId, setUnknownHandoffRequestId] = useState<string | null>(() =>
    initialTicketId
      ? globalThis.sessionStorage.getItem(handoffRecoveryStorageKey(initialTicketId))
      : null,
  );
  const [recoveringTicketId, setRecoveringTicketId] = useState<string | null>(initialTicketId);
  const requestId = useRef(globalThis.crypto.randomUUID());
  const intakeReplyRequestId = useRef(globalThis.crypto.randomUUID());
  const replyMessageId = useRef(globalThis.crypto.randomUUID());
  const resumeRequestId = useRef(globalThis.crypto.randomUUID());
  const handoffRequestId = useRef(globalThis.crypto.randomUUID());
  const ticketReplyRequestId = useRef(globalThis.crypto.randomUUID());
  const streamController = useRef<AbortController | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const snapshotRef = useRef<Snapshot | null>(null);

  useEffect(() => {
    const ticketId = initialTicketId;
    if (ticketId) {
      void loadTicket(ticketId).catch(() => {
        setError("暂时无法读取最新工单状态，我们会继续尝试从权威记录恢复。");
      });
    }
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
      const started = await humanSessionFetch(CUSTOMER_INTAKE_BASE, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          [csrf.headerName]: csrf.token,
          "Content-Type": "application/json",
          "Idempotency-Key": requestId.current,
        },
        body: JSON.stringify({
          schema: CUSTOMER_INTAKE_SCHEMA,
          message: orderReference
            ? `订单 ${orderReference} 的物流延迟问题：${description}`
            : description,
        }),
      });
      if (!started.ok && started.status !== 409) throw new Error("intake creation failed");
      const responseBody = (await started.json()) as unknown;
      const parsed = parseIntakeSnapshot(responseBody);
      if (!parsed) throw new Error("incompatible intake response");
      setIntake(parsed);
    } catch {
      setError("受理未完成，请保留本页并重试。相同请求不会创建第二张工单。");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitIntakeReply(event: FormEvent) {
    event.preventDefault();
    if (!intake || !intakeReply.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      await replyToIntake(intake, intakeReply);
      setIntakeReply("");
    } catch {
      setError("这次回复尚未确认，请重试原操作；相同请求不会重复创建工单。");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmIntake() {
    if (!intake) return;
    setSubmitting(true);
    setError("");
    try {
      await replyToIntake(intake, "确认提交");
    } catch {
      setError("确认结果尚未取得，请重试原确认；不会创建部分工单或重复工单。");
    } finally {
      setSubmitting(false);
    }
  }

  async function replyToIntake(current: IntakeSnapshot, message: string) {
    const csrf = await loadCsrfToken();
    const response = await humanSessionFetch(
      `${CUSTOMER_INTAKE_BASE}/${current.intakeId}/messages`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: {
          [csrf.headerName]: csrf.token,
          "Content-Type": "application/json",
          "Idempotency-Key": intakeReplyRequestId.current,
        },
        body: JSON.stringify({ schema: CUSTOMER_INTAKE_SCHEMA, message }),
      },
    );
    if (!response.ok && response.status !== 409) throw new Error("intake reply failed");
    const value = (await response.json()) as unknown;
    const parsed = parseIntakeSnapshot(value);
    if (!parsed) throw new Error("incompatible intake reply");
    setIntake(parsed);
    if (parsed.ticketIds.length === 1) {
      await loadTicket(parsed.ticketIds[0]);
      setIntake(null);
      return;
    }
    intakeReplyRequestId.current = globalThis.crypto.randomUUID();
  }

  async function loadTicket(ticketId: string) {
    const loaded = await humanSessionFetch(`${PUBLIC_CONVERSATION_BASE}/${ticketId}`, {
      credentials: "same-origin",
    });
    if (!loaded.ok) throw new Error("snapshot request failed");
    const authoritative = (await loaded.json()) as Snapshot;
    if (!isSnapshot(authoritative)) throw new Error("incompatible snapshot");
    snapshotRef.current = authoritative;
    setSnapshot(authoritative);
    setRecoveringTicketId(null);
    setCopiedTicketId(false);
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
      const response = await humanSessionFetch(
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
      const status = await humanSessionFetch(
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
      const response = await humanSessionFetch(`/api/customer/tickets/${ticketId}/human-handoff`, {
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
      forgetUnknownHandoff(ticketId);
    } catch {
      await reconcileHumanHandoff(ticketId, requestId);
    } finally {
      setSubmitting(false);
    }
  }

  async function queryHumanHandoffResult() {
    if (!snapshot || !unknownHandoffRequestId) return;
    setSubmitting(true);
    setError("");
    try {
      await reconcileHumanHandoff(snapshot.ticket.id, unknownHandoffRequestId);
    } finally {
      setSubmitting(false);
    }
  }

  async function reconcileHumanHandoff(ticketId: string, stableRequestId: string) {
    const status = await humanSessionFetch(
      `/api/customer/tickets/${ticketId}/human-handoff-requests/${stableRequestId}`,
      { credentials: "same-origin" },
    ).catch(() => null);
    if (!status?.ok) {
      rememberUnknownHandoff(ticketId, stableRequestId);
      setError("转人工结果仍在确认中。请只查询结果，不要重复提交转人工请求。");
      return;
    }
    try {
      await loadTicket(ticketId);
      handoffRequestId.current = globalThis.crypto.randomUUID();
      forgetUnknownHandoff(ticketId);
    } catch {
      rememberUnknownHandoff(ticketId, stableRequestId);
      setError("已找到转人工结果，但最新工单状态刷新失败；请再次查询权威结果。");
    }
  }

  function rememberUnknownHandoff(ticketId: string, stableRequestId: string) {
    globalThis.sessionStorage.setItem(handoffRecoveryStorageKey(ticketId), stableRequestId);
    setUnknownHandoffRequestId(stableRequestId);
  }

  function forgetUnknownHandoff(ticketId: string) {
    globalThis.sessionStorage.removeItem(handoffRecoveryStorageKey(ticketId));
    setUnknownHandoffRequestId(null);
  }

  async function submitTicketReply(event: FormEvent) {
    event.preventDefault();
    if (!snapshot || !["RESOLVED", "CLOSED"].includes(snapshot.ticket.lifecycleState)) return;
    setSubmitting(true);
    setError("");
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `/api/customer/tickets/${snapshot.ticket.id}/replies`,
        {
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
        },
      );
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
      if (!controller.signal.aborted) {
        snapshotRef.current = null;
        setSnapshot(null);
        setRecoveringTicketId(ticketId);
        setError("实时更新已断开，已清除可能过期的内容并重新同步权威状态。");
      }
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
      const response = await humanSessionFetch(`${PUBLIC_CONVERSATION_BASE}/${ticketId}/events`, {
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

  async function copyTicketId() {
    if (!snapshot) return;
    try {
      await globalThis.navigator.clipboard.writeText(snapshot.ticket.id);
      setCopiedTicketId(true);
    } catch {
      setError("完整工单编号复制失败，请稍后再试。");
    }
  }

  async function retryTicketRecovery() {
    if (!recoveringTicketId) return;
    setSubmitting(true);
    setError("");
    try {
      await loadTicket(recoveringTicketId);
    } catch {
      setError("仍未读取到最新工单状态，请稍后再次查询。");
    } finally {
      setSubmitting(false);
    }
  }

  const currentLifecyclePresentation = lifecyclePresentation(snapshot?.ticket.lifecycleState);

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
      envelope.view !== "PUBLIC_CONVERSATION" ||
      envelope.schema !== PUBLIC_CONVERSATION_SCHEMA ||
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
          直接描述你的问题。我们会先确认订单与理解；只有你明确确认后，才创建可查询的客服工单并开始处理。
        </p>
      </header>

      {!snapshot && recoveringTicketId ? (
        <section className="ticket-recovery" aria-live="polite" aria-busy="true">
          <span className="recovery-orbit" aria-hidden="true" />
          <p className="eyebrow">安全恢复</p>
          <h2>正在重新同步工单</h2>
          <p>旧内容已清除。我们正在从服务端重新读取最新状态，无需重复创建或提交操作。</p>
          <p className="ticket-reference">工单 {shortTicketId(recoveringTicketId)}</p>
          <button
            type="button"
            className="recovery-action"
            disabled={submitting}
            onClick={retryTicketRecovery}
          >
            {submitting ? "正在同步…" : "立即重试同步"}
          </button>
          {error && (
            <StatusNotice className="error" role="status" tone="warning">
              {error}
            </StatusNotice>
          )}
        </section>
      ) : !snapshot && intake ? (
        <section className="intake-card" aria-live="polite" aria-busy={submitting}>
          <div className="intake-agent-heading">
            <span className="intake-agent-mark" aria-hidden="true">
              澄
            </span>
            <div>
              <p className="eyebrow">智能受理</p>
              <h2>
                {intake.status === "CONFIRMED"
                  ? `${intake.ticketIds.length} 张工单已创建`
                  : intake.status === "READY_TO_CONFIRM"
                    ? intake.issues.length > 1
                      ? `请确认 ${intake.issues.length} 个问题`
                      : "请确认我的理解"
                    : "再帮我确认一点"}
              </h2>
            </div>
          </div>
          <p className="intake-agent-message">{intake.assistantMessage}</p>
          {intake.candidateOrder && (
            <article className="intake-candidate" aria-label="订单候选">
              <span className="intake-candidate-icon" aria-hidden="true">
                订
              </span>
              <div>
                <span>订单候选</span>
                <strong>{intake.candidateOrder.reference}</strong>
                <small>{intake.candidateOrder.summary}</small>
              </div>
              <span className="intake-candidate-boundary">仅摘要</span>
            </article>
          )}
          <div className="intake-issue-list" aria-label="拟建工单集">
            {intake.issues.map((issue, index) => (
              <article
                className="intake-issue"
                aria-label={intake.issues.length === 1 ? "问题理解" : `拟建工单 ${index + 1}`}
                key={issue.kind}
              >
                <span>
                  问题 {index + 1} · {intakeIssueLabel(issue.kind)}
                </span>
                <strong>{issue.summary}</strong>
                <small>
                  确认前不会创建正式工单。每张工单只有这个订单和一个问题，并保持独立状态与公开沟通。
                </small>
              </article>
            ))}
            {intake.issues.length === 0 && (
              <p className="intake-empty">尚无已确认理解的问题，请补充或纠正后继续。</p>
            )}
          </div>
          {intake.status !== "CONFIRMED" && (
            <p className="intake-atomic-note">
              确认前不会创建正式工单，也不会启动服务时长目标；确认时全部创建或一张也不创建。
            </p>
          )}
          {intake.status === "READY_TO_CONFIRM" && (
            <button
              className="primary-action"
              type="button"
              disabled={submitting}
              onClick={confirmIntake}
            >
              {submitting
                ? "正在原子创建…"
                : intake.issues.length > 1
                  ? `确认并原子创建 ${intake.issues.length} 张工单`
                  : "确认，就是这个问题"}
            </button>
          )}
          {intake.status === "CONFIRMED" && (
            <div className="intake-created-tickets" role="region" aria-label="已创建工单">
              {intake.ticketIds.map((ticketId, index) => (
                <button type="button" key={ticketId} onClick={() => void loadTicket(ticketId)}>
                  查看工单 {index + 1} · {shortTicketId(ticketId)}
                </button>
              ))}
            </div>
          )}
          {intake.status !== "CONFIRMED" && (
            <form className="intake-reply-form" onSubmit={submitIntakeReply}>
              <label>
                {intake.status === "READY_TO_CONFIRM"
                  ? "需要纠正？直接告诉我"
                  : "补充或纠正你的意思"}
                <textarea
                  aria-label="补充受理信息"
                  value={intakeReply}
                  onChange={(event) => setIntakeReply(event.target.value)}
                  placeholder="例如：不是这笔订单，是另一笔；或者直接回复“可以”"
                  required
                  rows={3}
                />
              </label>
              <button className="intake-secondary-action" disabled={submitting}>
                {submitting ? "正在理解…" : "发送给智能受理"}
              </button>
            </form>
          )}
          {error && (
            <StatusNotice className="error" role="alert" tone="danger">
              {error}
            </StatusNotice>
          )}
        </section>
      ) : !snapshot ? (
        <form className="ticket-form" onSubmit={submit}>
          <div className="form-intro">
            <span className="form-step">01</span>
            <div>
              <p className="eyebrow">自然语言受理</p>
              <h2>直接说说发生了什么</h2>
              <p>
                无需先选择问题类型。Agent 会依据你可见的订单摘要提出理解，得到确认后才创建工单。
              </p>
            </div>
          </div>
          <label>
            订单引用（可选）
            <input
              aria-label="订单编号"
              autoComplete="off"
              placeholder="例如 ORDER-DELAY-001"
              value={orderReference}
              onChange={(event) => setOrderReference(event.target.value)}
            />
          </label>
          <label>
            问题描述
            <textarea
              aria-label="问题描述"
              placeholder="请说明你遇到的问题，以及希望我们核实的内容"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              required
              rows={5}
            />
          </label>
          <button className="primary-action" disabled={submitting}>
            {submitting ? "正在理解你的问题…" : "提交物流延迟问题"}
          </button>
          <p className="form-assurance">此时只开始受理对话；确认前不会创建正式工单。</p>
          {error && (
            <StatusNotice className="error" role="alert" tone="danger">
              {error}
            </StatusNotice>
          )}
        </form>
      ) : (
        <section className="ticket-card" aria-live="polite">
          <div className="ticket-heading">
            <div className="ticket-identity">
              <p className="eyebrow">客服工单</p>
              <div className="ticket-id-row">
                <h2>{shortTicketId(snapshot.ticket.id)}</h2>
                <button
                  type="button"
                  className="copy-ticket-id"
                  aria-label="复制完整工单编号"
                  onClick={copyTicketId}
                >
                  {copiedTicketId ? "已复制" : "复制编号"}
                </button>
              </div>
            </div>
            <div className="ticket-state-summary">
              <span className={`status ${currentLifecyclePresentation.className}`}>
                {currentLifecyclePresentation.label}
              </span>
              <span className="handling-mode">
                {handlingModeLabel(snapshot.ticket.handlingMode)}
              </span>
            </div>
          </div>
          <div className="state-guidance">
            <span className="state-marker" aria-hidden="true" />
            <div>
              <strong>{currentLifecyclePresentation.title}</strong>
              <p>{currentLifecyclePresentation.description}</p>
            </div>
          </div>
          <div className="conversation-heading">
            <div>
              <p className="eyebrow">公开沟通</p>
              <h3>这张工单中的消息</h3>
            </div>
            <span>{snapshot.messages.length} 条</span>
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
            {snapshot.messages.length === 0 && (
              <li className="empty-conversation">新消息会在这里出现。</li>
            )}
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
            !["RESOLVED", "CLOSED"].includes(snapshot.ticket.lifecycleState) &&
            (unknownHandoffRequestId ? (
              <div className="handoff-reconciliation">
                <StatusNotice role="status" tone="warning">
                  转人工请求已经发出，但结果尚未确认。后续操作只会查询原请求的权威结果。
                </StatusNotice>
                <button
                  type="button"
                  className="handoff-button"
                  disabled={submitting}
                  onClick={queryHumanHandoffResult}
                >
                  {submitting ? "正在查询…" : "查询转人工结果"}
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="handoff-button"
                disabled={submitting}
                onClick={() => setConfirmingHumanHandoff(true)}
              >
                {submitting ? "正在提交…" : "转人工处理"}
              </button>
            ))}
          <Modal
            open={confirmingHumanHandoff}
            title="确认转人工处理"
            okText="确认转人工"
            cancelText="暂不转人工"
            onCancel={() => setConfirmingHumanHandoff(false)}
            onOk={() => {
              setConfirmingHumanHandoff(false);
              void requestHumanHandoff();
            }}
          >
            <p>确认后，当前工单将转由人工客服继续处理；系统不会承诺具体响应时间。</p>
          </Modal>
          <p className="recovery-note">刷新或重新连接后，本页只从权威快照恢复公开沟通。</p>
          {error && (
            <StatusNotice className="error" role="alert" tone="danger">
              {error}
            </StatusNotice>
          )}
        </section>
      )}
    </main>
  );
}

function isSnapshot(value: unknown): value is Snapshot {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ["view", "schema", "cursor", "ticket", "messages", "clarification"]) ||
    value.view !== "PUBLIC_CONVERSATION" ||
    value.schema !== PUBLIC_CONVERSATION_SCHEMA
  )
    return false;
  const cursor = typeof value.cursor === "string" ? parseCursor(value.cursor) : null;
  return (
    cursor?.epoch === value.schema &&
    isRecord(value.ticket) &&
    hasOnlyKeys(value.ticket, ["id", "lifecycleState", "handlingMode", "agentGeneration"]) &&
    typeof value.ticket.id === "string" &&
    typeof value.ticket.lifecycleState === "string" &&
    typeof value.ticket.handlingMode === "string" &&
    Array.isArray(value.messages) &&
    Number.isSafeInteger(value.ticket.agentGeneration) &&
    Number(value.ticket.agentGeneration) >= 0 &&
    value.messages.every(isPublicMessage) &&
    isClarification(value.clarification)
  );
}

function parseIntakeSnapshot(value: unknown): IntakeSnapshot | null {
  if (!isRecord(value)) return null;
  const legacy = value.schema === "customer-intake-v1";
  const expectedKeys = legacy
    ? [
        "schema",
        "intakeId",
        "status",
        "candidateOrder",
        "issue",
        "assistantMessage",
        "ticketId",
        "confirmed",
        "replayed",
      ]
    : [
        "schema",
        "intakeId",
        "status",
        "candidateOrder",
        "issue",
        "issues",
        "assistantMessage",
        "ticketId",
        "ticketIds",
        "sharedIntakeRecordId",
        "expectedTicketCount",
        "confirmed",
        "replayed",
      ];
  if (
    !hasOnlyKeys(value, expectedKeys) ||
    (!legacy && value.schema !== CUSTOMER_INTAKE_SCHEMA) ||
    typeof value.intakeId !== "string" ||
    !["READY_TO_CONFIRM", "NEEDS_CLARIFICATION", "CONFIRMED"].includes(String(value.status)) ||
    typeof value.assistantMessage !== "string" ||
    !(value.ticketId === null || typeof value.ticketId === "string") ||
    typeof value.confirmed !== "boolean" ||
    typeof value.replayed !== "boolean"
  )
    return null;
  const candidate = value.candidateOrder;
  const issue = value.issue;
  if (
    !(
      candidate === null ||
      (isRecord(candidate) &&
        hasOnlyKeys(candidate, ["reference", "summary"]) &&
        typeof candidate.reference === "string" &&
        typeof candidate.summary === "string")
    ) ||
    !(issue === null || isIntakeIssue(issue))
  )
    return null;
  const issues = legacy ? (issue ? [issue] : []) : value.issues;
  const ticketIds = legacy
    ? typeof value.ticketId === "string"
      ? [value.ticketId]
      : []
    : value.ticketIds;
  if (
    !Array.isArray(issues) ||
    !issues.every(isIntakeIssue) ||
    !Array.isArray(ticketIds) ||
    !ticketIds.every((ticketId) => typeof ticketId === "string") ||
    (!legacy &&
      (!(value.sharedIntakeRecordId === null || typeof value.sharedIntakeRecordId === "string") ||
        !Number.isSafeInteger(value.expectedTicketCount) ||
        Number(value.expectedTicketCount) !== issues.length))
  )
    return null;
  return {
    schema: legacy ? "customer-intake-v1" : CUSTOMER_INTAKE_SCHEMA,
    intakeId: value.intakeId,
    status: value.status as IntakeSnapshot["status"],
    candidateOrder: candidate as IntakeSnapshot["candidateOrder"],
    issue,
    issues,
    assistantMessage: value.assistantMessage,
    ticketId: value.ticketId,
    ticketIds,
    sharedIntakeRecordId: legacy ? null : (value.sharedIntakeRecordId as string | null),
    expectedTicketCount: legacy ? issues.length : Number(value.expectedTicketCount),
    confirmed: value.confirmed,
    replayed: value.replayed,
  };
}

function isIntakeIssue(value: unknown): value is IntakeIssue {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["kind", "summary"]) &&
    ["LOGISTICS_DELAY", "PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"].includes(String(value.kind)) &&
    typeof value.summary === "string"
  );
}

function intakeIssueLabel(kind: IntakeIssue["kind"]) {
  switch (kind) {
    case "PACKAGE_NOT_RECEIVED":
      return "包裹未收到";
    case "DUPLICATE_CHARGE":
      return "重复扣款";
    default:
      return "物流延迟";
  }
}

function parseCursor(cursor: string) {
  return parseViewCursor(cursor, PUBLIC_CONVERSATION_SCHEMA);
}

function isClarification(value: unknown): value is Snapshot["clarification"] {
  return (
    value === null ||
    (isRecord(value) &&
      hasOnlyKeys(value, ["id", "promptCode", "question"]) &&
      typeof value.id === "string" &&
      typeof value.promptCode === "string" &&
      typeof value.question === "string")
  );
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

function readRequestedTicketId() {
  const ticketId = new URLSearchParams(globalThis.location.search).get("ticket");
  return ticketId && /^[0-9a-f-]{36}$/i.test(ticketId) ? ticketId : null;
}

function shortTicketId(ticketId: string) {
  return ticketId.length === 36 ? `${ticketId.slice(0, 8)}…${ticketId.slice(-4)}` : ticketId;
}

function handlingModeLabel(handlingMode: string) {
  return handlingMode === "HUMAN" ? "人工客服处理中" : "智能客服处理中";
}

const LIFECYCLE_PRESENTATIONS: Record<
  string,
  { label: string; title: string; description: string; className: string }
> = {
  NEW: {
    label: "已受理",
    title: "工单已经收到",
    description: "我们正在准备调查，你无需重复提交。",
    className: "status-new",
  },
  INVESTIGATING: {
    label: "调查中",
    title: "我们正在核实情况",
    description: "调查会在后台继续，公开进展会更新到下方消息中。",
    className: "status-investigating",
  },
  WAITING_FOR_CUSTOMER: {
    label: "等待你的回复",
    title: "需要你补充一项信息",
    description: "请查看下方问题并回复；提交后我们会继续原调查。",
    className: "status-waiting_for_customer",
  },
  WAITING_FOR_EXTERNAL: {
    label: "等待外部信息",
    title: "正在等待外部信息",
    description: "当前无需操作，收到可公开的新信息后会继续更新。",
    className: "status-waiting_for_external",
  },
  RESOLVED: {
    label: "已解决",
    title: "本次处理已有结果",
    description: "请查看公开回复；如仍需说明，可使用下方现有回复入口。",
    className: "status-resolved",
  },
  CLOSED: {
    label: "已关闭",
    title: "本次工单已经结束",
    description: "历史公开回复仍可查看；如需继续反馈，可使用下方现有回复入口。",
    className: "status-closed",
  },
};

function lifecyclePresentation(lifecycleState?: string) {
  return (
    (lifecycleState ? LIFECYCLE_PRESENTATIONS[lifecycleState] : undefined) ?? {
      label: "状态更新中",
      title: "正在确认最新状态",
      description: "请以本页下一次权威更新为准。",
      className: "status-pending",
    }
  );
}

function handoffRecoveryStorageKey(ticketId: string) {
  return `customer-handoff-recovery:${ticketId}`;
}
