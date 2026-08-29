import { useEffect, useRef, useState } from "react";
import { loadCsrfToken } from "./csrf";
import { StatusNotice } from "./components/SystemState";
import { humanSessionFetch } from "./humanSessionLifecycle";
import { consumeSseEvents, hasOnlyKeys, isRecord, parseViewCursor } from "./streamProtocol";

const SCHEMA = "intake-assistance-v1" as const;
const statuses = ["QUEUED", "CLAIMED", "WAITING_FOR_CUSTOMER"] as const;
const issueKinds = [
  "LOGISTICS_DELAY",
  "PACKAGE_NOT_RECEIVED",
  "DUPLICATE_CHARGE",
  "ORDER_OPERATION_OR_RULE",
  "OTHER",
] as const;
type AssistanceStatus = (typeof statuses)[number];
type IssueKind = (typeof issueKinds)[number];

type QueueItem = {
  requestId: string;
  status: AssistanceStatus;
  reasonCode:
    "AGENT_UNAVAILABLE" | "TOOL_UNAVAILABLE" | "CUSTOMER_REQUESTED" | "UNSUPPORTED_REQUEST";
  requestedAt: string;
  claimExpiresAt: string | null;
  assignedToCurrentSupport: boolean;
};

type Snapshot = {
  view: "INTAKE_ASSISTANCE";
  schema: typeof SCHEMA;
  cursor: string;
  requests: QueueItem[];
};

type Details = {
  requestId: string;
  intakeId: string;
  status: "CLAIMED" | "WAITING_FOR_CUSTOMER";
  reasonCode: QueueItem["reasonCode"];
  originalMessage: string;
  orderCandidates: Array<{ reference: string; summary: string }>;
  selectedOrderReference: string | null;
  issues: Array<{ kind: IssueKind; summary: string }>;
  intakeVersion: number;
  claimExpiresAt: string;
};

type DraftIssues = Record<IssueKind, { selected: boolean; summary: string }>;

export function IntakeAssistancePanel() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connection, setConnection] = useState<"loading" | "live" | "stale">("loading");
  const [details, setDetails] = useState<Details | null>(null);
  const [selectedOrder, setSelectedOrder] = useState("");
  const [draftIssues, setDraftIssues] = useState<DraftIssues>(emptyIssues());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const stream = useRef<AbortController | null>(null);
  const authorityStream = useRef<AbortController | null>(null);
  const reconnect = useRef<number | null>(null);

  useEffect(() => {
    void loadSnapshot();
    return () => {
      stream.current?.abort();
      authorityStream.current?.abort();
      if (reconnect.current !== null) globalThis.clearTimeout(reconnect.current);
    };
  }, []);

  async function loadSnapshot() {
    stream.current?.abort();
    setConnection("loading");
    setError("");
    try {
      const response = await humanSessionFetch("/api/support/intake-assistance/snapshot", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error();
      const value = (await response.json()) as unknown;
      if (!isSnapshot(value)) throw new Error();
      setSnapshot(value);
      setConnection("live");
      void monitorQueue(value.cursor);
    } catch {
      setSnapshot(null);
      setConnection("stale");
      setError("受理协助队列加载失败；未沿用可能过期的本地数据。");
    }
  }

  async function monitorQueue(cursor: string) {
    const controller = new AbortController();
    stream.current = controller;
    try {
      const response = await humanSessionFetch("/api/support/intake-assistance/events", {
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "text/event-stream", "Last-Event-ID": cursor },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error();
      const continuous = await consumeSseEvents(response.body, (event) => {
        const parsed = parseViewCursor(event.id, SCHEMA);
        if (!parsed || !isAssistanceEvent(event.data)) return false;
        return false;
      });
      if (!continuous && !controller.signal.aborted) {
        await loadSnapshot();
        return;
      }
    } catch {
      // The authority snapshot is discarded below before a bounded reconnect.
    }
    if (controller.signal.aborted || stream.current !== controller) return;
    setSnapshot(null);
    setConnection("stale");
    setError("受理协助实时连接已断开；正在重新读取权威状态。");
    reconnect.current = globalThis.setTimeout(() => void loadSnapshot(), 250);
  }

  async function claim(item: QueueItem) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (!item.assignedToCurrentSupport) {
        const csrf = await loadCsrfToken();
        const response = await humanSessionFetch(
          `/api/support/intake-assistance/requests/${item.requestId}/claims`,
          {
            method: "POST",
            credentials: "same-origin",
            headers: { [csrf.headerName]: csrf.token },
          },
        );
        if (!response.ok) throw new Error();
      }
      await loadDetails(item.requestId);
    } catch {
      setDetails(null);
      setError("领取未完成或受理协助责任已失效，请重新同步。");
    } finally {
      setBusy(false);
    }
  }

  async function loadDetails(requestId: string) {
    const response = await humanSessionFetch(
      `/api/support/intake-assistance/requests/${requestId}`,
      { credentials: "same-origin", cache: "no-store" },
    );
    if (!response.ok) throw new Error();
    const value = (await response.json()) as unknown;
    if (!isDetails(value)) throw new Error();
    setDetails(value);
    setSelectedOrder(value.selectedOrderReference ?? value.orderCandidates[0]?.reference ?? "");
    setDraftIssues(toDraftIssues(value.issues));
    void monitorAuthority(requestId);
  }

  async function monitorAuthority(requestId: string) {
    authorityStream.current?.abort();
    const controller = new AbortController();
    authorityStream.current = controller;
    try {
      const response = await humanSessionFetch(
        `/api/support/intake-assistance/requests/${requestId}/events`,
        {
          credentials: "same-origin",
          cache: "no-store",
          headers: { Accept: "text/event-stream" },
          signal: controller.signal,
        },
      );
      if (!response.ok) throw new Error();
      await consumeSseEvents(response.body, () => false);
    } catch {
      // Re-read below so a stale responsibility never keeps detail visible.
    }
    if (controller.signal.aborted || authorityStream.current !== controller) return;
    try {
      await loadDetails(requestId);
    } catch {
      setDetails(null);
      setError("受理协助权限已撤销；旧详情已移除，请重新同步队列。");
    }
  }

  async function submitProposal() {
    if (!details) return;
    const issues = issueKinds
      .filter((kind) => draftIssues[kind].selected)
      .map((kind) => ({ kind, summary: draftIssues[kind].summary.trim() }));
    if (!selectedOrder || issues.length === 0 || issues.some((issue) => !issue.summary)) {
      setError("请选择订单候选，并为至少一个拟建问题填写摘要。");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `/api/support/intake-assistance/requests/${details.requestId}/proposal`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": globalThis.crypto.randomUUID(),
            [csrf.headerName]: csrf.token,
          },
          body: JSON.stringify({
            schema: SCHEMA,
            expectedIntakeVersion: details.intakeVersion,
            orderReference: selectedOrder,
            issues,
          }),
        },
      );
      if (!response.ok) throw new Error();
      const result = (await response.json()) as { intakeVersion?: unknown; status?: unknown };
      if (result.status !== "WAITING_FOR_CUSTOMER" || typeof result.intakeVersion !== "number") {
        throw new Error();
      }
      setDetails({
        ...details,
        status: "WAITING_FOR_CUSTOMER",
        intakeVersion: result.intakeVersion,
      });
      setMessage("已提交给客户确认；尚未创建正式工单。");
    } catch {
      setError("受理修正提交失败；请重新读取权威详情后再试。");
    } finally {
      setBusy(false);
    }
  }

  async function release() {
    if (!details) return;
    setBusy(true);
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `/api/support/intake-assistance/requests/${details.requestId}/release`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: { [csrf.headerName]: csrf.token },
        },
      );
      if (!response.ok) throw new Error();
      authorityStream.current?.abort();
      setDetails(null);
      await loadSnapshot();
    } catch {
      setError("释放失败；当前责任可能已经变化，请重新同步。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="intake-assistance-panel" aria-labelledby="intake-assistance-title">
      <header>
        <div>
          <p className="eyebrow">INTAKE ASSISTANCE</p>
          <h2 id="intake-assistance-title">受理协助队列</h2>
          <p>协助确认订单与拟建问题；受理协助不是客服工单，也不授予调查或补偿权限。</p>
        </div>
        <StatusNotice
          className={`connection-state ${connection}`}
          tone={connection === "live" ? "success" : connection === "loading" ? "busy" : "danger"}
          role={connection === "stale" ? "alert" : "status"}
        >
          {connection === "loading" && "正在读取受理协助权威快照…"}
          {connection === "live" && "受理协助已与 Spring 权威状态同步"}
          {connection === "stale" && (error || "受理协助实时状态不可用")}
        </StatusNotice>
      </header>

      <div className={`intake-assistance-layout${details ? " has-detail" : ""}`}>
        <section className="queue-panel" aria-label="待处理受理协助">
          <header>
            <div>
              <p className="queue-kicker">INTAKE</p>
              <h3>待处理受理协助</h3>
              <p>领取前仅展示裁剪摘要</p>
            </div>
            <strong>{snapshot?.requests.length.toString().padStart(2, "0") ?? "--"}</strong>
          </header>
          {snapshot && snapshot.requests.length > 0 ? (
            <ul className="intake-assistance-list">
              {snapshot.requests.map((item) => (
                <li key={item.requestId}>
                  <div>
                    <strong>{reasonLabel(item.reasonCode)}</strong>
                    <span>{statusLabel(item.status)}</span>
                    <time dateTime={item.requestedAt}>{formatTime(item.requestedAt)}</time>
                  </div>
                  <button
                    type="button"
                    disabled={busy || (item.status !== "QUEUED" && !item.assignedToCurrentSupport)}
                    aria-label={`${item.assignedToCurrentSupport ? "继续" : "领取"}受理协助 ${item.requestId}`}
                    onClick={() => void claim(item)}
                  >
                    {item.assignedToCurrentSupport ? "继续协助" : "领取"}
                  </button>
                </li>
              ))}
            </ul>
          ) : snapshot ? (
            <p className="empty-queue">当前没有待处理的受理协助</p>
          ) : null}
        </section>

        {details ? (
          <article className="intake-assistance-detail" aria-labelledby="assistance-detail-title">
            <header>
              <div>
                <p className="eyebrow">CURRENT RESPONSIBILITY</p>
                <h3 id="assistance-detail-title">协助确认受理</h3>
              </div>
              <span>{statusLabel(details.status)}</span>
            </header>
            <section>
              <h4>客户原始诉求</h4>
              <p>{details.originalMessage}</p>
            </section>
            <label>
              订单候选
              <select
                value={selectedOrder}
                onChange={(event) => setSelectedOrder(event.target.value)}
              >
                <option value="">请选择</option>
                {details.orderCandidates.map((candidate) => (
                  <option key={candidate.reference} value={candidate.reference}>
                    {candidate.reference} · {candidate.summary}
                  </option>
                ))}
              </select>
            </label>
            <fieldset>
              <legend>拟建问题</legend>
              {issueKinds.map((kind) => (
                <div className="assistance-issue-editor" key={kind}>
                  <label>
                    <input
                      type="checkbox"
                      aria-label={issueLabel(kind)}
                      checked={draftIssues[kind].selected}
                      onChange={(event) =>
                        setDraftIssues({
                          ...draftIssues,
                          [kind]: { ...draftIssues[kind], selected: event.target.checked },
                        })
                      }
                    />
                    {issueLabel(kind)}
                  </label>
                  {draftIssues[kind].selected && (
                    <input
                      aria-label={`${issueLabel(kind)}摘要`}
                      value={draftIssues[kind].summary}
                      onChange={(event) =>
                        setDraftIssues({
                          ...draftIssues,
                          [kind]: { ...draftIssues[kind], summary: event.target.value },
                        })
                      }
                    />
                  )}
                </div>
              ))}
            </fieldset>
            <p className="authorization-note">客服提交后仍需客户确认；此操作不会创建工单。</p>
            <div className="intake-assistance-actions">
              <button type="button" disabled={busy} onClick={() => void submitProposal()}>
                提交给客户确认
              </button>
              <button type="button" disabled={busy} onClick={() => void release()}>
                释放协助
              </button>
            </div>
          </article>
        ) : (
          <aside className="detail-placeholder" aria-label="受理协助详情等待区">
            <p className="eyebrow">SCOPED DETAIL</p>
            <h3>领取后查看受理所需信息</h3>
            <p>不会显示完整订单事实、工单调查、公开回复、补偿或审批数据。</p>
          </aside>
        )}
      </div>
      {message && <p role="status">{message}</p>}
      {error && connection !== "stale" && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="button" onClick={() => void loadSnapshot()} disabled={connection === "loading"}>
        重新同步受理协助
      </button>
    </section>
  );
}

function emptyIssues(): DraftIssues {
  return {
    LOGISTICS_DELAY: { selected: false, summary: "" },
    PACKAGE_NOT_RECEIVED: { selected: false, summary: "" },
    DUPLICATE_CHARGE: { selected: false, summary: "" },
    ORDER_OPERATION_OR_RULE: { selected: false, summary: "" },
    OTHER: { selected: false, summary: "" },
  };
}

function toDraftIssues(issues: Details["issues"]): DraftIssues {
  const draft = emptyIssues();
  for (const issue of issues) draft[issue.kind] = { selected: true, summary: issue.summary };
  return draft;
}

function isSnapshot(value: unknown): value is Snapshot {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["view", "schema", "cursor", "requests"]) &&
    value.view === "INTAKE_ASSISTANCE" &&
    value.schema === SCHEMA &&
    typeof value.cursor === "string" &&
    parseViewCursor(value.cursor, SCHEMA) !== null &&
    Array.isArray(value.requests) &&
    value.requests.every(isQueueItem)
  );
}

function isQueueItem(value: unknown): value is QueueItem {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "requestId",
      "status",
      "reasonCode",
      "requestedAt",
      "claimExpiresAt",
      "assignedToCurrentSupport",
    ]) &&
    isUuid(value.requestId) &&
    typeof value.status === "string" &&
    statuses.some((status) => status === value.status) &&
    typeof value.reasonCode === "string" &&
    ["AGENT_UNAVAILABLE", "TOOL_UNAVAILABLE", "CUSTOMER_REQUESTED", "UNSUPPORTED_REQUEST"].includes(
      value.reasonCode,
    ) &&
    typeof value.requestedAt === "string" &&
    (value.claimExpiresAt === null || typeof value.claimExpiresAt === "string") &&
    typeof value.assignedToCurrentSupport === "boolean"
  );
}

function isDetails(value: unknown): value is Details {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "requestId",
      "intakeId",
      "status",
      "reasonCode",
      "originalMessage",
      "orderCandidates",
      "selectedOrderReference",
      "issues",
      "intakeVersion",
      "claimExpiresAt",
    ]) &&
    isUuid(value.requestId) &&
    isUuid(value.intakeId) &&
    (value.status === "CLAIMED" || value.status === "WAITING_FOR_CUSTOMER") &&
    typeof value.reasonCode === "string" &&
    typeof value.originalMessage === "string" &&
    Array.isArray(value.orderCandidates) &&
    value.orderCandidates.every(isOrderCandidate) &&
    (value.selectedOrderReference === null || typeof value.selectedOrderReference === "string") &&
    Array.isArray(value.issues) &&
    value.issues.every(isIssue) &&
    typeof value.intakeVersion === "number" &&
    Number.isSafeInteger(value.intakeVersion) &&
    typeof value.claimExpiresAt === "string"
  );
}

function isOrderCandidate(value: unknown) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["reference", "summary"]) &&
    typeof value.reference === "string" &&
    typeof value.summary === "string"
  );
}

function isIssue(value: unknown): value is Details["issues"][number] {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["kind", "summary"]) &&
    typeof value.kind === "string" &&
    issueKinds.some((kind) => kind === value.kind) &&
    typeof value.summary === "string"
  );
}

function isAssistanceEvent(data: string) {
  try {
    const value = JSON.parse(data) as unknown;
    return (
      isRecord(value) &&
      hasOnlyKeys(value, ["view", "schema", "payload"]) &&
      value.view === "INTAKE_ASSISTANCE" &&
      value.schema === SCHEMA &&
      isRecord(value.payload)
    );
  } catch {
    return false;
  }
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
}

function reasonLabel(reason: QueueItem["reasonCode"]) {
  return {
    AGENT_UNAVAILABLE: "Agent 暂不可用",
    TOOL_UNAVAILABLE: "受理工具暂不可用",
    CUSTOMER_REQUESTED: "客户请求人工协助",
    UNSUPPORTED_REQUEST: "超出自动识别范围",
  }[reason];
}

function statusLabel(status: AssistanceStatus) {
  return {
    QUEUED: "待领取",
    CLAIMED: "协助中",
    WAITING_FOR_CUSTOMER: "等待客户确认",
  }[status];
}

function issueLabel(kind: IssueKind) {
  return {
    LOGISTICS_DELAY: "物流延迟",
    PACKAGE_NOT_RECEIVED: "包裹未收到",
    DUPLICATE_CHARGE: "重复扣款",
    ORDER_OPERATION_OR_RULE: "地址或取消规则",
    OTHER: "其他问题",
  }[kind];
}

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}
