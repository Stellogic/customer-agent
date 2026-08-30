import { FormEvent, useEffect, useRef, useState } from "react";
import { Modal } from "antd";
import { Bubble, Conversations, Sender, Sources } from "@ant-design/x";
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
import { OrderTicketGroups } from "./OrderTicketGroups";
import { CustomerCapabilityGuide, CustomerTrustStrip } from "./components/CustomerHelpTrust";

const PUBLIC_CONVERSATION_SCHEMA = "public-conversation-v2" as const;
const PUBLIC_CONVERSATION_BASE = "/api/customer/v2/tickets";
const CUSTOMER_INTAKE_SCHEMA = "customer-intake-v4" as const;
const CUSTOMER_INTAKE_BASE = "/api/customer/v2/intakes";
const CUSTOMER_INTAKE_RECOVERY_SCHEMA = "customer-intake-recovery-v1" as const;

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
  replyStream?: {
    status: "LOADING" | "STREAMING" | "COMPLETED" | "ABORTED" | "FAILED";
    body: string;
    progressStage: "UNDERSTANDING" | "VERIFYING_FACTS" | "QUERYING_RULES" | "COMPOSING_REPLY";
  } | null;
  pendingCompensation?: {
    compensationMethod: string;
    amount: string;
    currency: string;
    status: "PENDING_REVIEW";
  } | null;
};

type EventEnvelope = {
  view: "PUBLIC_CONVERSATION";
  schema: typeof PUBLIC_CONVERSATION_SCHEMA;
  generation: number;
  payload: unknown;
};

type IntakeSnapshot = {
  schema:
    | "customer-intake-v1"
    | "customer-intake-v2"
    | "customer-intake-v3"
    | typeof CUSTOMER_INTAKE_SCHEMA;
  intakeId: string;
  status: "READY_TO_CONFIRM" | "NEEDS_CLARIFICATION" | "CONFIRMED";
  candidateOrder: { reference: string; summary: string } | null;
  issue: IntakeIssue | null;
  issues: IntakeIssue[];
  assistantMessage: string;
  ticketId: string | null;
  ticketIds: string[];
  sharedIntakeRecordId: string | null;
  duplicateMatches: DuplicateIntakeMatch[];
  routedTicketIds: string[];
  remainingOrderCount: number;
  completedOrderCount: number;
  expectedTicketCount: number;
  confirmed: boolean;
  version: number;
  replayed: boolean;
};

type IntakeIssue = {
  kind:
    | "LOGISTICS_DELAY"
    | "PACKAGE_NOT_RECEIVED"
    | "DUPLICATE_CHARGE"
    | "ORDER_OPERATION_OR_RULE"
    | "OTHER";
  summary: string;
};

type DuplicateIntakeMatch = {
  ticketId: string;
  issueKind: IntakeIssue["kind"];
  issueSummary: string;
  lifecycleState: string;
};

type RecoverableIntake = {
  intake: IntakeSnapshot;
  version: number;
  retentionState: "ACTIVE" | "ARCHIVED" | "COMPLETED";
  expiresAt: string | null;
  archivedAt: string | null;
  factsChanged: boolean;
  messages: Array<{ author: "CUSTOMER" | "AGENT"; body: string; sentAt: string }>;
};

type IntakeRecoveryIndex = {
  schema: typeof CUSTOMER_INTAKE_RECOVERY_SCHEMA;
  active: RecoverableIntake[];
  archived: RecoverableIntake[];
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
  const [intakeRecoveryState, setIntakeRecoveryState] = useState<
    "idle" | "loading" | "empty" | "ready" | "restoring" | "error"
  >("idle");
  const [archivedIntakes, setArchivedIntakes] = useState<RecoverableIntake[]>([]);
  const [intakeFactsChanged, setIntakeFactsChanged] = useState(false);
  const [intakeMessages, setIntakeMessages] = useState<RecoverableIntake["messages"]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [clarificationAnswer, setClarificationAnswer] = useState("");
  const [ticketReplyOrderReference, setTicketReplyOrderReference] = useState("");
  const [ticketReplyIssueKind, setTicketReplyIssueKind] = useState("LOGISTICS_DELAY");
  const [ticketReplyBody, setTicketReplyBody] = useState("");
  const [liveMessageBody, setLiveMessageBody] = useState("");
  const [liveMessageState, setLiveMessageState] = useState<
    "idle" | "sending" | "accepted" | "conflict" | "error"
  >("idle");
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
  const duplicateResolutionRequestId = useRef(globalThis.crypto.randomUUID());
  const restoreIntakeRequestId = useRef(globalThis.crypto.randomUUID());
  const replyMessageId = useRef(globalThis.crypto.randomUUID());
  const resumeRequestId = useRef(globalThis.crypto.randomUUID());
  const handoffRequestId = useRef(globalThis.crypto.randomUUID());
  const ticketReplyRequestId = useRef(globalThis.crypto.randomUUID());
  const liveMessageRequestId = useRef(globalThis.crypto.randomUUID());
  const streamController = useRef<AbortController | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const snapshotRef = useRef<Snapshot | null>(null);
  const initialIntakeId = readRequestedIntakeId();

  useEffect(() => {
    const ticketId = initialTicketId;
    if (ticketId) {
      void loadTicket(ticketId).catch(() => {
        setError("暂时无法读取最新工单状态，我们会继续尝试从权威记录恢复。");
      });
    } else if (initialIntakeId) {
      void loadIntake(initialIntakeId).catch(() => {
        setError("暂时无法恢复受理进度，请稍后重试权威记录。");
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
      setIntakeMessages([]);
      setIntakeFactsChanged(false);
      globalThis.history.replaceState(null, "", `?intake=${parsed.intakeId}`);
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
        body: JSON.stringify({
          schema: CUSTOMER_INTAKE_SCHEMA,
          message,
          expectedVersion: current.version,
        }),
      },
    );
    if (!response.ok && response.status !== 409) throw new Error("intake reply failed");
    const value = (await response.json()) as unknown;
    const parsed = parseIntakeSnapshot(value);
    if (!parsed) throw new Error("incompatible intake reply");
    setIntake(parsed);
    if (
      parsed.status === "CONFIRMED" &&
      parsed.ticketIds.length === 1 &&
      parsed.routedTicketIds.length === 0
    ) {
      await loadTicket(parsed.ticketIds[0]);
      setIntake(null);
      return;
    }
    intakeReplyRequestId.current = globalThis.crypto.randomUUID();
  }

  async function loadIntake(intakeId: string) {
    const response = await humanSessionFetch(`${CUSTOMER_INTAKE_BASE}/${intakeId}/recovery`, {
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error("intake snapshot failed");
    const recovered = parseRecoverableIntake((await response.json()) as unknown);
    if (!recovered) throw new Error("incompatible intake snapshot");
    setIntakeMessages(recovered.messages);
    setIntakeFactsChanged(recovered.factsChanged);
    if (recovered.retentionState === "ARCHIVED") {
      setIntake(null);
      setArchivedIntakes([recovered]);
      setIntakeRecoveryState("ready");
      return;
    }
    setIntake(recovered.intake);
    setIntakeRecoveryState("idle");
  }

  async function findRecoverableIntakes() {
    setIntakeRecoveryState("loading");
    setError("");
    try {
      const response = await humanSessionFetch(`${CUSTOMER_INTAKE_BASE}/recovery`, {
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("intake recovery index failed");
      const index = parseIntakeRecoveryIndex((await response.json()) as unknown);
      if (!index) throw new Error("incompatible intake recovery index");
      if (index.active.length > 0) {
        const active = index.active[0];
        setIntake(active.intake);
        setIntakeFactsChanged(active.factsChanged);
        setIntakeMessages(active.messages);
        globalThis.history.replaceState(null, "", `?intake=${active.intake.intakeId}`);
        setIntakeRecoveryState("idle");
        return;
      }
      setArchivedIntakes(index.archived);
      setIntakeRecoveryState(index.archived.length === 0 ? "empty" : "ready");
    } catch {
      setIntakeRecoveryState("error");
    }
  }

  async function restoreArchivedIntake(archived: RecoverableIntake) {
    setIntakeRecoveryState("restoring");
    setError("");
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `${CUSTOMER_INTAKE_BASE}/${archived.intake.intakeId}/restore`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            [csrf.headerName]: csrf.token,
            "Content-Type": "application/json",
            "Idempotency-Key": restoreIntakeRequestId.current,
          },
          body: JSON.stringify({
            schema: CUSTOMER_INTAKE_RECOVERY_SCHEMA,
            expectedVersion: archived.version,
          }),
        },
      );
      if (!response.ok) throw new Error("intake restore failed");
      const restored = parseRecoverableIntake((await response.json()) as unknown);
      if (!restored || restored.retentionState !== "ACTIVE") {
        throw new Error("incompatible intake restore");
      }
      setIntake(restored.intake);
      setIntakeFactsChanged(restored.factsChanged);
      setIntakeMessages(restored.messages);
      setArchivedIntakes([]);
      setIntakeRecoveryState("idle");
      globalThis.history.replaceState(null, "", `?intake=${restored.intake.intakeId}`);
      restoreIntakeRequestId.current = globalThis.crypto.randomUUID();
    } catch {
      setIntakeRecoveryState("error");
    }
  }

  async function resolveDuplicate(match: DuplicateIntakeMatch, action: string) {
    if (!intake) return;
    setSubmitting(true);
    setError("");
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `${CUSTOMER_INTAKE_BASE}/${intake.intakeId}/duplicate-resolution`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            [csrf.headerName]: csrf.token,
            "Content-Type": "application/json",
            "Idempotency-Key": duplicateResolutionRequestId.current,
          },
          body: JSON.stringify({
            schema: CUSTOMER_INTAKE_SCHEMA,
            existingTicketId: match.ticketId,
            action,
            expectedVersion: intake.version,
          }),
        },
      );
      if (!response.ok && response.status !== 409) throw new Error("duplicate resolution failed");
      const parsed = parseIntakeSnapshot((await response.json()) as unknown);
      if (!parsed) throw new Error("incompatible duplicate resolution");
      setIntake(parsed);
      duplicateResolutionRequestId.current = globalThis.crypto.randomUUID();
    } catch {
      setError("重复问题确认结果尚未取得；请重试同一操作，系统不会静默合并或重复建单。");
    } finally {
      setSubmitting(false);
    }
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

  async function refreshPendingCompensationSnapshot(ticketId: string, minimumCursor: string) {
    const requestedCursor = parseCursor(minimumCursor);
    if (!requestedCursor) return;
    try {
      const loaded = await humanSessionFetch(`${PUBLIC_CONVERSATION_BASE}/${ticketId}`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!loaded.ok) return;
      const authoritative = (await loaded.json()) as unknown;
      if (!isSnapshot(authoritative) || authoritative.ticket.id !== ticketId) return;
      const current = snapshotRef.current;
      const authoritativeCursor = parseCursor(authoritative.cursor);
      const currentCursor = current ? parseCursor(current.cursor) : null;
      if (
        !current ||
        current.ticket.id !== ticketId ||
        !authoritativeCursor ||
        !currentCursor ||
        authoritativeCursor.epoch !== requestedCursor.epoch ||
        authoritativeCursor.sequence < requestedCursor.sequence ||
        authoritativeCursor.epoch !== currentCursor.epoch ||
        authoritativeCursor.sequence < currentCursor.sequence
      )
        return;
      snapshotRef.current = authoritative;
      setSnapshot(authoritative);
    } catch {
      // Keep the last committed snapshot; the active SSE stream remains the recovery path.
    }
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

  async function submitLiveMessage(event: FormEvent) {
    event.preventDefault();
    if (
      !snapshot ||
      snapshot.ticket.handlingMode !== "AGENT" ||
      ["RESOLVED", "CLOSED"].includes(snapshot.ticket.lifecycleState) ||
      !liveMessageBody.trim()
    )
      return;
    const ticketId = snapshot.ticket.id;
    setLiveMessageState("sending");
    setError("");
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(`${PUBLIC_CONVERSATION_BASE}/${ticketId}/messages`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          [csrf.headerName]: csrf.token,
          "Content-Type": "application/json",
          "Idempotency-Key": liveMessageRequestId.current,
        },
        body: JSON.stringify({
          schema: PUBLIC_CONVERSATION_SCHEMA,
          message: liveMessageBody.trim(),
        }),
      });
      if (response.status === 409) {
        setLiveMessageState("conflict");
        await loadTicket(ticketId);
        return;
      }
      if (!response.ok) throw new Error("customer message failed");
      const result = (await response.json()) as unknown;
      if (
        !isRecord(result) ||
        result.schema !== PUBLIC_CONVERSATION_SCHEMA ||
        result.ticketId !== ticketId ||
        result.accepted !== true ||
        typeof result.replayed !== "boolean"
      )
        throw new Error("incompatible customer message result");
      await loadTicket(ticketId);
      setLiveMessageBody("");
      liveMessageRequestId.current = globalThis.crypto.randomUUID();
      setLiveMessageState("accepted");
    } catch {
      setLiveMessageState("error");
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
    const payload = envelope.payload;
    let next: Snapshot;
    let refreshPendingCompensation = false;
    if (
      event.type === "AGENT_PROCESSING_STARTED" &&
      envelope.generation > current.ticket.agentGeneration
    ) {
      if (!isProcessingState(payload)) return false;
      next = {
        ...current,
        cursor: event.id,
        ticket: { ...current.ticket, agentGeneration: envelope.generation },
        replyStream: { status: "LOADING", body: "", progressStage: "UNDERSTANDING" },
      };
      setLiveMessageState("accepted");
    } else if (envelope.generation > current.ticket.agentGeneration) {
      return false;
    } else if (
      event.type === "PUBLIC_MESSAGE_APPENDED" ||
      event.type === "CUSTOMER_MESSAGE_ACCEPTED"
    ) {
      if (!isPublicMessage(payload)) return false;
      const message = payload;
      refreshPendingCompensation =
        current.pendingCompensation !== undefined &&
        current.pendingCompensation !== null &&
        message.author === "SUPPORT";
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
          replyStream: current.replyStream,
        };
      }
    } else if (event.type === "AGENT_PROCESSING_TERMINATED") {
      if (!isProcessingTermination(payload)) return false;
      next = {
        ...current,
        cursor: event.id,
        replyStream: { status: "ABORTED", body: "", progressStage: "UNDERSTANDING" },
      };
      setLiveMessageState("accepted");
    } else if (event.type === "AGENT_PROCESSING_STARTED") {
      if (!isProcessingState(payload)) return false;
      next = {
        ...current,
        cursor: event.id,
        replyStream: { status: "LOADING", body: "", progressStage: "UNDERSTANDING" },
      };
    } else if (event.type === "AGENT_REPLY_LOADING") {
      if (!isReplyStatus(payload, "LOADING")) return false;
      next = {
        ...current,
        cursor: event.id,
        replyStream: { status: "LOADING", body: "", progressStage: "UNDERSTANDING" },
      };
    } else if (event.type === "PUBLIC_PROGRESS_UPDATED") {
      if (!isProgress(payload)) return false;
      next = {
        ...current,
        cursor: event.id,
        replyStream: {
          status: current.replyStream?.status ?? "LOADING",
          body: current.replyStream?.body ?? "",
          progressStage: payload.stage,
        },
      };
    } else if (event.type === "AGENT_REPLY_STREAM_STARTED") {
      if (!isReplyStatus(payload, "STREAMING")) return false;
      next = {
        ...current,
        cursor: event.id,
        replyStream: {
          status: "STREAMING",
          body: current.replyStream?.body ?? "",
          progressStage: current.replyStream?.progressStage ?? "COMPOSING_REPLY",
        },
      };
    } else if (event.type === "AGENT_REPLY_CONTENT_DELTA") {
      if (!isContentDelta(payload) || current.replyStream?.status !== "STREAMING") return false;
      next = {
        ...current,
        cursor: event.id,
        replyStream: {
          ...current.replyStream,
          body: current.replyStream.body + payload.delta,
        },
      };
    } else if (
      event.type === "AGENT_REPLY_COMPLETED" ||
      event.type === "AGENT_REPLY_ABORTED" ||
      event.type === "AGENT_REPLY_FAILED"
    ) {
      const expected =
        event.type === "AGENT_REPLY_COMPLETED"
          ? "COMPLETED"
          : event.type === "AGENT_REPLY_ABORTED"
            ? "ABORTED"
            : "FAILED";
      if (!isReplyStatus(payload, expected)) return false;
      if (expected === "COMPLETED" && !current.replyStream) {
        next = { ...current, cursor: event.id };
      } else {
        next = {
          ...current,
          cursor: event.id,
          replyStream: {
            status: expected,
            body: expected === "COMPLETED" ? (current.replyStream?.body ?? "") : "",
            progressStage: current.replyStream?.progressStage ?? "COMPOSING_REPLY",
          },
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
        replyStream:
          current.replyStream &&
          !["COMPLETED", "ABORTED", "FAILED"].includes(current.replyStream.status)
            ? { status: "FAILED", body: "", progressStage: "COMPOSING_REPLY" }
            : current.replyStream,
      };
    } else if (event.type === "COMPENSATION_REVIEW_PENDING") {
      const pending = parsePendingCompensation(payload);
      if (!pending) return false;
      next = { ...current, cursor: event.id, pendingCompensation: pending };
    } else if (event.type === "COMPENSATION_REVIEW_CLEARED") {
      if (!isCompensationReviewCleared(payload)) return false;
      next = { ...current, cursor: event.id, pendingCompensation: null };
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
        pendingCompensation: null,
      };
    } else {
      return false;
    }
    snapshotRef.current = next;
    setSnapshot(next);
    if (refreshPendingCompensation) {
      void refreshPendingCompensationSnapshot(current.ticket.id, event.id);
    }
    return true;
  }

  const showingHelpHome =
    !snapshot && !intake && recoveringTicketId === null && intakeRecoveryState === "idle";

  return (
    <main className="help-center">
      <div className="help-center-intro">
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

        {showingHelpHome && <CustomerTrustStrip />}
        {showingHelpHome && (
          <OrderTicketGroups autoLoad onOpenTicket={(ticketId) => void loadTicket(ticketId)} />
        )}
      </div>

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
      ) : !snapshot && intakeRecoveryState !== "idle" ? (
        <section
          className="ticket-recovery intake-recovery"
          aria-live="polite"
          aria-busy={intakeRecoveryState === "loading" || intakeRecoveryState === "restoring"}
        >
          <p className="eyebrow">受理记录</p>
          {intakeRecoveryState === "loading" && (
            <StatusNotice role="status" tone="busy">
              正在查找活动与已归档受理
            </StatusNotice>
          )}
          {intakeRecoveryState === "restoring" && (
            <StatusNotice role="status" tone="warning">
              正在恢复受理并核对当前订单事实
            </StatusNotice>
          )}
          {intakeRecoveryState === "ready" && (
            <>
              <h2>已归档受理</h2>
              <p>七日保留期已结束。恢复只会重新核对事实，不会直接确认或创建工单。</p>
              <div className="archived-intake-list">
                {archivedIntakes.map((archived) => (
                  <article key={archived.intake.intakeId}>
                    <strong>{archived.intake.candidateOrder?.reference ?? "待确认订单"}</strong>
                    <span>
                      {archived.messages.at(-1)?.body ?? archived.intake.assistantMessage}
                    </span>
                    <button type="button" onClick={() => void restoreArchivedIntake(archived)}>
                      恢复并重新核对事实
                    </button>
                  </article>
                ))}
              </div>
            </>
          )}
          {intakeRecoveryState === "empty" && (
            <>
              <h2>没有可恢复的受理记录</h2>
              <p>当前客户没有活动或已归档的未确认受理，你可以开始新的受理对话。</p>
              <button type="button" onClick={() => void findRecoverableIntakes()}>
                重新查询受理记录
              </button>
            </>
          )}
          {intakeRecoveryState === "error" && (
            <>
              <StatusNotice role="alert" tone="danger">
                受理记录加载失败，请稍后重新读取 Spring 权威记录。
              </StatusNotice>
              <button type="button" onClick={() => void findRecoverableIntakes()}>
                重新查询受理记录
              </button>
            </>
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
                {intake.duplicateMatches.length > 0
                  ? "请确认是否继续既有工单"
                  : intake.status === "CONFIRMED"
                    ? intake.ticketIds.length > 0
                      ? `${intake.ticketIds.length} 张工单已创建`
                      : "已继续既有工单"
                    : intake.completedOrderCount > 0
                      ? "继续下一订单"
                      : intake.status === "READY_TO_CONFIRM"
                        ? intake.issues.length > 1
                          ? `请确认 ${intake.issues.length} 个问题`
                          : "请确认我的理解"
                        : "再帮我确认一点"}
              </h2>
            </div>
          </div>
          {intakeFactsChanged && intake.status !== "CONFIRMED" && (
            <StatusNotice role="status" tone="warning">
              订单事实已变化，请重新确认
            </StatusNotice>
          )}
          {intakeMessages.length > 0 && (
            <ol className="intake-transcript" aria-label="已恢复的受理消息">
              {intakeMessages.map((message, index) => (
                <li key={`${message.sentAt}-${index}`}>
                  <span>{message.author === "CUSTOMER" ? "我" : "智能受理"}</span>
                  <p>{message.body}</p>
                </li>
              ))}
            </ol>
          )}
          <p className="intake-agent-message">{intake.assistantMessage}</p>
          {(intake.completedOrderCount > 0 || intake.remainingOrderCount > 0) && (
            <p className="intake-atomic-note" role="status">
              已逐订单完成 {intake.completedOrderCount} 个，仍有 {intake.remainingOrderCount}{" "}
              个待续办； 原始描述已保留，但下一订单仍需单独确认。
            </p>
          )}
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
          {intake.duplicateMatches.length > 0 && (
            <div className="intake-duplicate-list" role="region" aria-label="疑似重复问题">
              {intake.duplicateMatches.map((match) => (
                <article className="intake-issue" key={`${match.issueKind}-${match.ticketId}`}>
                  <span>疑似重复 · {intakeIssueLabel(match.issueKind)}</span>
                  <strong>{match.issueSummary}</strong>
                  <small>
                    仅使用同一订单下未关闭工单的编号、问题类型与状态匹配；不会读取或合并既有对话。
                  </small>
                  <div className="intake-duplicate-actions">
                    <button
                      type="button"
                      disabled={submitting}
                      onClick={() => void resolveDuplicate(match, "CONTINUE_EXISTING")}
                    >
                      继续旧工单 {shortTicketId(match.ticketId)}
                    </button>
                  </div>
                </article>
              ))}
              <button
                className="intake-secondary-action"
                type="button"
                disabled={submitting}
                onClick={() => {
                  const firstMatch = intake.duplicateMatches[0];
                  if (firstMatch) void resolveDuplicate(firstMatch, "CREATE_NEW");
                }}
              >
                这是新问题，继续创建
              </button>
            </div>
          )}
          {intake.status !== "CONFIRMED" && (
            <p className="intake-atomic-note">
              确认前不会创建正式工单，也不会启动服务时长目标；确认时全部创建或一张也不创建。
            </p>
          )}
          {intake.status === "READY_TO_CONFIRM" && intake.duplicateMatches.length === 0 && (
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
          {intake.ticketIds.length > 1 && (
            <OrderTicketGroups autoLoad onOpenTicket={(ticketId) => void loadTicket(ticketId)} />
          )}
          {intake.ticketIds.length === 1 && (
            <div className="intake-created-tickets" role="region" aria-label="已创建工单">
              {intake.ticketIds.map((ticketId, index) => (
                <button type="button" key={ticketId} onClick={() => void loadTicket(ticketId)}>
                  查看工单 {index + 1} · {shortTicketId(ticketId)}
                </button>
              ))}
            </div>
          )}
          {intake.routedTicketIds.length > 0 && (
            <div className="intake-created-tickets" role="region" aria-label="继续处理的既有工单">
              {intake.routedTicketIds.map((ticketId) => (
                <button type="button" key={ticketId} onClick={() => void loadTicket(ticketId)}>
                  继续旧工单 · {shortTicketId(ticketId)}
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
          <button
            type="button"
            className="intake-secondary-action"
            onClick={() => void findRecoverableIntakes()}
          >
            查找未完成受理
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
          {snapshot.pendingCompensation && (
            <aside
              className="pending-compensation-card"
              aria-labelledby="pending-compensation-title"
            >
              <p className="eyebrow">补偿建议</p>
              <h3 id="pending-compensation-title">待审批</h3>
              <dl>
                <div>
                  <dt>建议类型</dt>
                  <dd>
                    {compensationMethodLabel(snapshot.pendingCompensation.compensationMethod)}
                  </dd>
                </div>
                <div>
                  <dt>建议金额</dt>
                  <dd>
                    {snapshot.pendingCompensation.amount} {snapshot.pendingCompensation.currency}
                  </dd>
                </div>
                <div>
                  <dt>当前状态</dt>
                  <dd>待审批</dd>
                </div>
              </dl>
              <p>最终结果将在处理完成后通知你。现在还没有批准或执行补偿。</p>
            </aside>
          )}
          <div className="conversation-heading">
            <div>
              <p className="eyebrow">公开沟通</p>
              <h3>这张工单中的消息</h3>
            </div>
            <span>{snapshot.messages.length} 条</span>
          </div>
          <Conversations
            rootClassName="ticket-conversation-selector"
            aria-label="当前工单会话"
            activeKey={snapshot.ticket.id}
            items={[{ key: snapshot.ticket.id, label: "当前公开沟通" }]}
          />
          <div className="conversation" role="log" aria-live="polite">
            {snapshot.messages
              .filter(
                (message) =>
                  !(
                    message.author === "AGENT" &&
                    snapshot.replyStream?.status === "COMPLETED" &&
                    snapshot.replyStream.body === message.body
                  ),
              )
              .map((message, index) => (
                <Bubble
                  key={`${message.sentAt}-${index}`}
                  placement={message.author === "CUSTOMER" ? "end" : "start"}
                  variant={message.author === "AGENT" ? "outlined" : "filled"}
                  content={message.body}
                  header={
                    message.author === "CUSTOMER"
                      ? "你"
                      : message.author === "AGENT"
                        ? "智能客服"
                        : "客服"
                  }
                />
              ))}
            {snapshot.replyStream && (
              <>
                <Bubble
                  key={`stream-${snapshot.ticket.agentGeneration}`}
                  placement="start"
                  variant="outlined"
                  content={
                    snapshot.replyStream.body || progressLabel(snapshot.replyStream.progressStage)
                  }
                  header="智能客服"
                  loading={snapshot.replyStream.status === "LOADING"}
                  streaming={snapshot.replyStream.status === "STREAMING"}
                  footer={
                    snapshot.replyStream.status === "LOADING"
                      ? undefined
                      : replyStreamFooter(snapshot.replyStream.status)
                  }
                />
                {snapshot.replyStream.status === "LOADING" && (
                  <p className="reply-stream-status" role="status">
                    等待首个内容片段
                  </p>
                )}
                {["STREAMING", "COMPLETED"].includes(snapshot.replyStream.status) && (
                  <Sources
                    rootClassName="reply-sources"
                    title="本次回复依据"
                    defaultExpanded
                    items={[
                      { key: "conversation", title: "当前工单公开对话" },
                      { key: "business-facts", title: "已核对的订单与物流事实" },
                      { key: "policy", title: "适用的客服规则" },
                    ]}
                  />
                )}
              </>
            )}
          </div>
          {snapshot.messages.length === 0 && !snapshot.replyStream && (
            <p className="empty-conversation">新消息会在这里出现。</p>
          )}
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
          {snapshot.ticket.handlingMode === "AGENT" &&
            !["RESOLVED", "CLOSED"].includes(snapshot.ticket.lifecycleState) && (
              <form className="clarification-form live-message-form" onSubmit={submitLiveMessage}>
                <label className="sender-label">
                  继续补充消息
                  <Sender
                    rootClassName="customer-message-sender"
                    placeholder="继续补充消息"
                    value={liveMessageBody}
                    loading={liveMessageState === "sending"}
                    suffix={false}
                    onChange={(value) => {
                      setLiveMessageBody(value);
                      if (liveMessageState !== "sending") setLiveMessageState("idle");
                    }}
                    onSubmit={() => {
                      if (liveMessageBody.trim()) {
                        document
                          .querySelector<HTMLFormElement>(".live-message-form")
                          ?.requestSubmit();
                      }
                    }}
                  />
                </label>
                <button disabled={liveMessageState === "sending"}>
                  {liveMessageState === "sending" ? "正在发送…" : "发送新消息"}
                </button>
                {liveMessageState === "accepted" && (
                  <StatusNotice role="status" tone="success">
                    已接受你的补充，旧回复已停止，正在结合最新对话重新处理。
                  </StatusNotice>
                )}
                {liveMessageState === "conflict" && (
                  <StatusNotice role="alert" tone="warning">
                    工单状态已经变化，已重新同步；请确认当前状态后再发送。
                  </StatusNotice>
                )}
                {liveMessageState === "error" && (
                  <StatusNotice role="alert" tone="danger">
                    消息结果暂时未知。请保留原文并重试；系统会复用稳定消息身份，不会重复追加。
                  </StatusNotice>
                )}
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
                  <option value="PACKAGE_NOT_RECEIVED">包裹未收到</option>
                  <option value="DUPLICATE_CHARGE">重复扣款</option>
                  <option value="ORDER_OPERATION_OR_RULE">地址或取消规则</option>
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
      {showingHelpHome && <CustomerCapabilityGuide />}
    </main>
  );
}

function isSnapshot(value: unknown): value is Snapshot {
  if (
    !isRecord(value) ||
    value.view !== "PUBLIC_CONVERSATION" ||
    value.schema !== PUBLIC_CONVERSATION_SCHEMA
  )
    return false;
  const keys = Object.keys(value);
  const required = ["view", "schema", "cursor", "ticket", "messages", "clarification"];
  if (!required.every((key) => keys.includes(key))) return false;
  if (
    keys.some(
      (key) => !required.includes(key) && key !== "replyStream" && key !== "pendingCompensation",
    )
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
    isClarification(value.clarification) &&
    (value.replyStream === undefined || isReplyStream(value.replyStream)) &&
    (value.pendingCompensation === undefined ||
      value.pendingCompensation === null ||
      parsePendingCompensation(value.pendingCompensation) !== null)
  );
}

function parsePendingCompensation(
  value: unknown,
): NonNullable<Snapshot["pendingCompensation"]> | null {
  if (!isRecord(value)) return null;
  const keys = Object.keys(value);
  const allowed = ["compensationMethod", "amount", "currency", "status"];
  if (
    !["compensationMethod", "amount", "status"].every((key) => keys.includes(key)) ||
    keys.some((key) => !allowed.includes(key)) ||
    typeof value.compensationMethod !== "string" ||
    value.status !== "PENDING_REVIEW" ||
    (value.currency !== undefined && value.currency !== "CNY")
  )
    return null;
  const amount =
    typeof value.amount === "number" && Number.isFinite(value.amount)
      ? value.amount.toFixed(2)
      : typeof value.amount === "string"
        ? value.amount
        : null;
  if (!amount || !/^\d+\.\d{2}$/.test(amount)) return null;
  return {
    compensationMethod: value.compensationMethod,
    amount,
    currency: "CNY",
    status: "PENDING_REVIEW",
  };
}

function isReplyStream(value: unknown): value is NonNullable<Snapshot["replyStream"]> | null {
  return (
    value === null ||
    (isRecord(value) &&
      hasOnlyKeys(value, ["status", "body", "progressStage"]) &&
      ["LOADING", "STREAMING", "COMPLETED", "ABORTED", "FAILED"].includes(String(value.status)) &&
      typeof value.body === "string" &&
      value.body.length <= 1_000 &&
      ["UNDERSTANDING", "VERIFYING_FACTS", "QUERYING_RULES", "COMPOSING_REPLY"].includes(
        String(value.progressStage),
      ))
  );
}

function isReplyStatus(value: unknown, status: string) {
  return isRecord(value) && hasOnlyKeys(value, ["status"]) && value.status === status;
}

function isCompensationReviewCleared(value: unknown) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["status"]) &&
    (value.status === "APPROVED" || value.status === "REJECTED")
  );
}

function isProgress(
  value: unknown,
): value is { stage: NonNullable<Snapshot["replyStream"]>["progressStage"] } {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["stage"]) &&
    ["UNDERSTANDING", "VERIFYING_FACTS", "QUERYING_RULES", "COMPOSING_REPLY"].includes(
      String(value.stage),
    )
  );
}

function isContentDelta(value: unknown): value is { chunkIndex: number; delta: string } {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["chunkIndex", "delta"]) &&
    Number.isSafeInteger(value.chunkIndex) &&
    Number(value.chunkIndex) >= 0 &&
    typeof value.delta === "string" &&
    value.delta.length > 0 &&
    value.delta.length <= 512
  );
}

function progressLabel(stage: NonNullable<Snapshot["replyStream"]>["progressStage"]) {
  return {
    UNDERSTANDING: "正在理解问题",
    VERIFYING_FACTS: "正在核对业务事实",
    QUERYING_RULES: "正在查询规则",
    COMPOSING_REPLY: "正在整理回复",
  }[stage];
}

function replyStreamFooter(status: NonNullable<Snapshot["replyStream"]>["status"]) {
  return {
    LOADING: "等待首个内容片段",
    STREAMING: "正在接收回复",
    COMPLETED: "回复已完成",
    ABORTED: "旧回复已终止",
    FAILED: "回复失败，正在转人工处理",
  }[status];
}

function isProcessingTermination(value: unknown) {
  return (
    isRecord(value) && hasOnlyKeys(value, ["reason"]) && value.reason === "NEW_CUSTOMER_MESSAGE"
  );
}

function isProcessingState(value: unknown) {
  return isRecord(value) && hasOnlyKeys(value, ["state"]) && value.state === "PROCESSING";
}

function parseIntakeRecoveryIndex(value: unknown): IntakeRecoveryIndex | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ["schema", "active", "archived"]) ||
    value.schema !== CUSTOMER_INTAKE_RECOVERY_SCHEMA ||
    !Array.isArray(value.active) ||
    !Array.isArray(value.archived)
  )
    return null;
  const active = value.active.map(parseRecoverableIntake);
  const archived = value.archived.map(parseRecoverableIntake);
  if (active.some((item) => item === null) || archived.some((item) => item === null)) return null;
  const parsedActive = active as RecoverableIntake[];
  const parsedArchived = archived as RecoverableIntake[];
  if (
    parsedActive.some((item) => item.retentionState !== "ACTIVE") ||
    parsedArchived.some((item) => item.retentionState !== "ARCHIVED")
  )
    return null;
  return {
    schema: CUSTOMER_INTAKE_RECOVERY_SCHEMA,
    active: parsedActive,
    archived: parsedArchived,
  };
}

function parseRecoverableIntake(value: unknown): RecoverableIntake | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "intake",
      "version",
      "retentionState",
      "expiresAt",
      "archivedAt",
      "factsChanged",
      "messages",
    ]) ||
    !Number.isSafeInteger(value.version) ||
    Number(value.version) < 1 ||
    !["ACTIVE", "ARCHIVED", "COMPLETED"].includes(String(value.retentionState)) ||
    !(value.archivedAt === null || typeof value.archivedAt === "string") ||
    typeof value.factsChanged !== "boolean" ||
    !Array.isArray(value.messages) ||
    !value.messages.every(isIntakeConversationMessage)
  )
    return null;
  if (
    (value.retentionState === "COMPLETED" && value.expiresAt !== null) ||
    (value.retentionState !== "COMPLETED" && typeof value.expiresAt !== "string")
  )
    return null;
  const intake = parseIntakeSnapshot(value.intake);
  if (!intake) return null;
  return {
    intake,
    version: Number(value.version),
    retentionState: value.retentionState as RecoverableIntake["retentionState"],
    expiresAt: value.expiresAt as string | null,
    archivedAt: value.archivedAt,
    factsChanged: value.factsChanged,
    messages: value.messages as RecoverableIntake["messages"],
  };
}

function isIntakeConversationMessage(value: unknown) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["author", "body", "sentAt"]) &&
    ["CUSTOMER", "AGENT"].includes(String(value.author)) &&
    typeof value.body === "string" &&
    typeof value.sentAt === "string"
  );
}

function parseIntakeSnapshot(value: unknown): IntakeSnapshot | null {
  if (!isRecord(value)) return null;
  const legacy = value.schema === "customer-intake-v1";
  const v2 = value.schema === "customer-intake-v2";
  const v3 = value.schema === "customer-intake-v3";
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
    : v2
      ? [
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
        ]
      : v3
        ? [
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
            "duplicateMatches",
            "routedTicketIds",
            "remainingOrderCount",
            "completedOrderCount",
            "expectedTicketCount",
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
            "duplicateMatches",
            "routedTicketIds",
            "remainingOrderCount",
            "completedOrderCount",
            "expectedTicketCount",
            "confirmed",
            "version",
            "replayed",
          ];
  if (
    !hasOnlyKeys(value, expectedKeys) ||
    (!legacy && !v2 && !v3 && value.schema !== CUSTOMER_INTAKE_SCHEMA) ||
    typeof value.intakeId !== "string" ||
    !["READY_TO_CONFIRM", "NEEDS_CLARIFICATION", "CONFIRMED"].includes(String(value.status)) ||
    typeof value.assistantMessage !== "string" ||
    !(value.ticketId === null || typeof value.ticketId === "string") ||
    typeof value.confirmed !== "boolean" ||
    (!legacy &&
      !v2 &&
      !v3 &&
      (!Number.isSafeInteger(value.version) || Number(value.version) < 1)) ||
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
  const duplicateMatches = legacy || v2 ? [] : value.duplicateMatches;
  const routedTicketIds = legacy || v2 ? [] : value.routedTicketIds;
  if (
    !Array.isArray(issues) ||
    !issues.every(isIntakeIssue) ||
    !Array.isArray(ticketIds) ||
    !ticketIds.every((ticketId) => typeof ticketId === "string") ||
    !Array.isArray(duplicateMatches) ||
    !duplicateMatches.every(isDuplicateIntakeMatch) ||
    !Array.isArray(routedTicketIds) ||
    !routedTicketIds.every((ticketId) => typeof ticketId === "string") ||
    (!legacy &&
      !v2 &&
      (!Number.isSafeInteger(value.remainingOrderCount) ||
        Number(value.remainingOrderCount) < 0 ||
        !Number.isSafeInteger(value.completedOrderCount) ||
        Number(value.completedOrderCount) < 0)) ||
    (!legacy &&
      (!(value.sharedIntakeRecordId === null || typeof value.sharedIntakeRecordId === "string") ||
        !Number.isSafeInteger(value.expectedTicketCount) ||
        Number(value.expectedTicketCount) !== issues.length))
  )
    return null;
  return {
    schema: legacy
      ? "customer-intake-v1"
      : v2
        ? "customer-intake-v2"
        : v3
          ? "customer-intake-v3"
          : CUSTOMER_INTAKE_SCHEMA,
    intakeId: value.intakeId,
    status: value.status as IntakeSnapshot["status"],
    candidateOrder: candidate as IntakeSnapshot["candidateOrder"],
    issue,
    issues,
    assistantMessage: value.assistantMessage,
    ticketId: value.ticketId,
    ticketIds,
    sharedIntakeRecordId: legacy ? null : (value.sharedIntakeRecordId as string | null),
    duplicateMatches,
    routedTicketIds,
    remainingOrderCount: legacy || v2 ? 0 : Number(value.remainingOrderCount),
    completedOrderCount: legacy || v2 ? 0 : Number(value.completedOrderCount),
    expectedTicketCount: legacy ? issues.length : Number(value.expectedTicketCount),
    confirmed: value.confirmed,
    version: legacy || v2 || v3 ? 0 : Number(value.version),
    replayed: value.replayed,
  };
}

function isDuplicateIntakeMatch(value: unknown): value is DuplicateIntakeMatch {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["ticketId", "issueKind", "issueSummary", "lifecycleState"]) &&
    typeof value.ticketId === "string" &&
    isIntakeIssue({ kind: value.issueKind, summary: value.issueSummary }) &&
    typeof value.lifecycleState === "string"
  );
}

function isIntakeIssue(value: unknown): value is IntakeIssue {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["kind", "summary"]) &&
    [
      "LOGISTICS_DELAY",
      "PACKAGE_NOT_RECEIVED",
      "DUPLICATE_CHARGE",
      "ORDER_OPERATION_OR_RULE",
      "OTHER",
    ].includes(String(value.kind)) &&
    typeof value.summary === "string"
  );
}

function intakeIssueLabel(kind: IntakeIssue["kind"]) {
  switch (kind) {
    case "PACKAGE_NOT_RECEIVED":
      return "包裹未收到";
    case "DUPLICATE_CHARGE":
      return "重复扣款";
    case "ORDER_OPERATION_OR_RULE":
      return "地址或取消规则";
    case "OTHER":
      return "其他问题";
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

function readRequestedIntakeId() {
  const intakeId = new URLSearchParams(globalThis.location.search).get("intake");
  return intakeId && /^[0-9a-f-]{36}$/i.test(intakeId) ? intakeId : null;
}

function shortTicketId(ticketId: string) {
  return ticketId.length === 36 ? `${ticketId.slice(0, 8)}…${ticketId.slice(-4)}` : ticketId;
}

function handlingModeLabel(handlingMode: string) {
  return handlingMode === "HUMAN" ? "人工客服处理中" : "智能客服处理中";
}

function compensationMethodLabel(method: string) {
  if (method === "COUPON") return "优惠券";
  if (method === "SIMULATED_PARTIAL_REFUND") return "模拟原路部分退款";
  return method;
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
