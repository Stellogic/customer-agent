import { useEffect, useRef, useState } from "react";
import { StatusNotice } from "./components/SystemState";
import { loadCsrfToken } from "./csrf";
import { humanSessionFetch } from "./humanSessionLifecycle";
import {
  consumeSseEvents,
  hasOnlyKeys,
  isRecord,
  parseViewCursor,
  type SseEvent,
} from "./streamProtocol";

const SCHEMA = "approval-view-v1" as const;
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
type ResponsibilityEvent = {
  eventType: string;
  actorId: string;
  occurredAt: string;
  leaseVersion: number | null;
};
type Snapshot = {
  view: "APPROVAL_VIEW";
  schema: typeof SCHEMA;
  cursor: string;
  proposalRevisionId: string;
  proposalRevision: number;
  contentDigest: string;
  orderReference: string;
  reasonCode: string;
  delayHours: number;
  delaySeconds: number;
  compensationMethod: string;
  proposedAmount: number;
  authoritativeAmount: number;
  policyVersion: string;
  policyTier: string;
  eligibilityChecks: string[];
  evidenceReferences: string[];
  evidenceSnapshot: Record<string, unknown>;
  responsibilityChain: ResponsibilityEvent[];
  leaseToken: string;
  leaseVersion: number;
  leaseExpiresAt: string;
  submittedAt: string;
  proposalExpiresAt: string;
};
type Tone = "neutral" | "success" | "busy" | "warning" | "danger";
type Status = { message: string; tone: Tone };
type Action = "approve" | "reject" | "release" | null;
const status = (message: string, tone: Tone): Status => ({ message, tone });

export function ApprovalWorkbench() {
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [notice, setNotice] = useState(status("正在读取待审批队列…", "busy"));
  const [action, setAction] = useState<Action>(null);
  const [claimingId, setClaimingId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const leaseRef = useRef<Lease | null>(null);
  const streamRef = useRef<AbortController | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const claimAttemptRef = useRef(0);
  const activeClaimRef = useRef<number | null>(null);

  useEffect(() => {
    globalThis.history.replaceState(null, "", "/internal/approvals");
    void loadQueue();
    return clearTimers;
  }, []);

  async function loadQueue() {
    try {
      const response = await humanSessionFetch("/api/approver/compensation-proposals", {
        credentials: "same-origin",
        cache: "no-store",
      });
      const value = response.ok ? ((await response.json()) as unknown) : null;
      if (!Array.isArray(value) || !value.every(isQueueItem)) throw new Error();
      setQueue(value);
      setNotice(status("待审批队列已刷新", "success"));
    } catch {
      setNotice(status("待审批队列暂时不可用", "danger"));
    }
  }

  async function claim(id: string) {
    if (activeClaimRef.current !== null) return;
    const attempt = ++claimAttemptRef.current;
    activeClaimRef.current = attempt;
    setClaimingId(id);
    clearTimers();
    leaseRef.current = null;
    setSnapshot(null);
    setAction(null);
    setNotice(status("正在领取审批责任…", "busy"));
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `/api/approver/compensation-proposals/${id}/claims`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            [csrf.headerName]: csrf.token,
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify({ requestedLeaseSeconds: 900 }),
        },
      );
      const lease = response.ok ? ((await response.json()) as unknown) : null;
      if (activeClaimRef.current !== attempt) return;
      if (!isLease(lease)) throw new Error();
      leaseRef.current = lease;
      history.replaceState(null, "", `/internal/approvals?revision=${id}`);
      await loadView(lease);
    } catch {
      if (activeClaimRef.current === attempt)
        revoke(status("审批责任不可用，已返回队列。", "danger"));
    } finally {
      if (activeClaimRef.current === attempt) {
        activeClaimRef.current = null;
        setClaimingId(null);
      }
    }
  }

  async function loadView(lease: Lease) {
    try {
      const response = await humanSessionFetch(
        `/api/approver/compensation-proposals/${lease.proposalRevisionId}/approval-view`,
        {
          credentials: "same-origin",
          cache: "no-store",
          headers: leaseHeaders(lease),
        },
      );
      if (!response.ok) {
        revoke(status("审批责任已结束，证据和操作已移除。", "warning"));
        await loadQueue();
        return;
      }
      const value = (await response.json()) as unknown;
      if (
        !isSnapshot(value) ||
        value.leaseToken !== lease.leaseToken ||
        value.leaseVersion !== lease.leaseVersion ||
        value.proposalRevisionId !== lease.proposalRevisionId
      )
        throw new Error();
      setSnapshot(value);
      setNotice(status("审批证据已与 Spring 权威状态同步", "success"));
      void consumeEvents(lease, value.cursor);
    } catch {
      recover(lease);
    }
  }

  async function consumeEvents(lease: Lease, cursor: string) {
    const controller = new AbortController();
    streamRef.current = controller;
    try {
      const response = await humanSessionFetch(
        `/api/approver/compensation-proposals/${lease.proposalRevisionId}/approval-view/events`,
        {
          credentials: "same-origin",
          cache: "no-store",
          signal: controller.signal,
          headers: { ...leaseHeaders(lease), "Last-Event-ID": cursor, Accept: "text/event-stream" },
        },
      );
      if ([401, 403, 404, 410].includes(response.status)) {
        revoke(status("审批责任已结束，证据和操作已移除。", "warning"));
        return;
      }
      if (response.status === 409) {
        setSnapshot(null);
        await loadView(lease);
        return;
      }
      if (!response.ok) throw new Error();
      const compatible = await consumeSseEvents(response.body, (event) => {
        if (!validEvent(event, lease, cursor)) return false;
        cursor = event.id;
        return true;
      });
      if (!compatible) {
        controller.abort();
        setSnapshot(null);
        await loadView(lease);
        return;
      }
      recover(lease);
    } catch {
      if (!controller.signal.aborted) recover(lease);
    }
  }

  function recover(lease: Lease) {
    if (leaseRef.current?.leaseToken !== lease.leaseToken || reconnectRef.current !== null) return;
    setSnapshot(null);
    setAction(null);
    history.replaceState(null, "", "/internal/approvals");
    setNotice(status("审批连接已断开；正在按当前租约重新校验权威快照…", "warning"));
    reconnectRef.current = window.setTimeout(() => {
      reconnectRef.current = null;
      if (leaseRef.current?.leaseToken === lease.leaseToken) void loadView(lease);
    }, 250);
  }

  async function decide(kind: "approve" | "reject") {
    const lease = leaseRef.current,
      current = snapshot;
    if (!lease || !current) return;
    setAction(null);
    setSnapshot(null);
    try {
      const csrf = await loadCsrfToken();
      const response = await humanSessionFetch(
        `/api/approver/compensation-proposals/${lease.proposalRevisionId}/${kind}`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            ...leaseHeaders(lease),
            [csrf.headerName]: csrf.token,
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify({
            proposalRevision: current.proposalRevision,
            contentDigest: current.contentDigest,
            ...(kind === "approve"
              ? { internalNote: note.trim() || undefined }
              : { internalReason: reason.trim() }),
          }),
        },
      );
      if (!response.ok) {
        revoke(status("审批责任已失效，证据和操作已移除。", "danger"));
        await loadQueue();
        return;
      }
      revoke(status("审批责任已结束，已返回队列。", "success"));
      await loadQueue();
      setNotice(status("审批责任已结束，已返回队列。", "success"));
    } catch {
      setNotice(status("结果尚未确认，正在恢复 Spring 权威状态…", "warning"));
      await loadView(lease);
    }
  }

  async function release() {
    const lease = leaseRef.current;
    if (!lease) return;
    setAction(null);
    setSnapshot(null);
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
            "Idempotency-Key": crypto.randomUUID(),
          },
        },
      );
      if (!response.ok) {
        revoke(status("审批责任已失效，证据和操作已移除。", "danger"));
        await loadQueue();
        return;
      }
      revoke(status("审批责任已释放，已返回队列。", "success"));
      await loadQueue();
      setNotice(status("审批责任已释放，已返回队列。", "success"));
    } catch {
      setNotice(status("结果尚未确认，正在恢复 Spring 权威状态…", "warning"));
      await loadView(lease);
    }
  }

  function clearTimers() {
    streamRef.current?.abort();
    streamRef.current = null;
    if (reconnectRef.current !== null) clearTimeout(reconnectRef.current);
    reconnectRef.current = null;
  }
  function revoke(next: Status, resetPath = true) {
    claimAttemptRef.current += 1;
    activeClaimRef.current = null;
    setClaimingId(null);
    clearTimers();
    leaseRef.current = null;
    setSnapshot(null);
    setAction(null);
    setReason("");
    setNote("");
    setNotice(next);
    if (resetPath) history.replaceState(null, "", "/internal/approvals");
  }

  return (
    <main className="approval-workbench" aria-label="审批工作台">
      <header className="approval-workbench-header">
        <div>
          <p className="eyebrow">APPROVAL CONTROL</p>
          <h1>{snapshot ? "补偿提案审批" : "待审批补偿"}</h1>
          <p>审批证据仅在当前有效租约内加载；Spring 始终是授权与金额的权威来源。</p>
        </div>
        <StatusNotice
          className="approval-connection-state"
          tone={notice.tone}
          role={notice.tone === "danger" ? "alert" : "status"}
        >
          {notice.message}
        </StatusNotice>
      </header>
      {snapshot ? (
        <Detail snapshot={snapshot} onAction={setAction} />
      ) : (
        <Queue queue={queue} claimingId={claimingId} onClaim={(id) => void claim(id)} />
      )}
      {action && snapshot ? (
        <Confirmation
          action={action}
          snapshot={snapshot}
          reason={reason}
          note={note}
          setReason={setReason}
          setNote={setNote}
          cancel={() => setAction(null)}
          confirm={() => (action === "release" ? void release() : void decide(action))}
        />
      ) : null}
    </main>
  );
}

function Queue({
  queue,
  claimingId,
  onClaim,
}: {
  queue: QueueItem[];
  claimingId: string | null;
  onClaim: (id: string) => void;
}) {
  return (
    <section className="approval-queue" aria-label="审批队列">
      <header>
        <div>
          <p className="queue-kicker">可领取提案</p>
          <h2>真实待审批摘要</h2>
        </div>
        <strong>{queue.length} 项</strong>
      </header>
      {queue.length ? (
        <div className="approval-table" role="table" aria-label="待审批提案">
          <div className="approval-table-row approval-table-heading" role="row">
            <span role="columnheader">提案 UUID</span>
            <span role="columnheader">补偿方式</span>
            <span role="columnheader">金额</span>
            <span role="columnheader">提交时间</span>
            <span role="columnheader">操作</span>
          </div>
          {queue.map((item) => (
            <div className="approval-table-row" role="row" key={item.proposalRevisionId}>
              <span role="cell" className="approval-uuid-cell">
                <code title={item.proposalRevisionId}>{shortUuid(item.proposalRevisionId)}</code>
                <button
                  type="button"
                  className="copy-button"
                  aria-label="复制完整提案 UUID"
                  onClick={() => void navigator.clipboard?.writeText(item.proposalRevisionId)}
                >
                  复制
                </button>
              </span>
              <span role="cell">{displayCode(item.compensationMethod)}</span>
              <strong role="cell">{money(item.amount)}</strong>
              <time role="cell" dateTime={item.submittedAt}>
                {displayTime(item.submittedAt)}
              </time>
              <span role="cell">
                <button
                  type="button"
                  disabled={claimingId !== null}
                  onClick={() => onClaim(item.proposalRevisionId)}
                >
                  {claimingId === item.proposalRevisionId ? "正在领取" : "领取审批"}
                </button>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="approval-empty">当前没有待审批提案</p>
      )}
    </section>
  );
}

function Detail({
  snapshot,
  onAction,
}: {
  snapshot: Snapshot;
  onAction: (value: Exclude<Action, null>) => void;
}) {
  return (
    <div className="approval-detail-grid">
      <section className="approval-card approval-summary">
        <header>
          <div>
            <p className="queue-kicker">提案摘要</p>
            <h2>{snapshot.orderReference}</h2>
          </div>
          <span className="approval-lease-badge">租约 v{snapshot.leaseVersion}</span>
        </header>
        <dl className="approval-facts">
          <Fact name="提案 UUID">
            <code title={snapshot.proposalRevisionId}>
              {shortUuid(snapshot.proposalRevisionId)}
            </code>
            <button
              type="button"
              className="copy-button"
              onClick={() => void navigator.clipboard?.writeText(snapshot.proposalRevisionId)}
            >
              复制完整值
            </button>
          </Fact>
          <Fact name="补偿方式">{displayCode(snapshot.compensationMethod)}</Fact>
          <Fact name="提案金额">{money(snapshot.proposedAmount)}</Fact>
          <Fact name="提案版本">第 {snapshot.proposalRevision} 版</Fact>
          <Fact name="原因代码">{snapshot.reasonCode}</Fact>
          <Fact name="延迟事实">
            {snapshot.delayHours} 小时（{snapshot.delaySeconds} 秒）
          </Fact>
        </dl>
      </section>
      <section className="approval-card approval-authority">
        <p className="queue-kicker">资格与金额</p>
        <h2>权威金额</h2>
        <strong className="authority-amount">{money(snapshot.authoritativeAmount)}</strong>
        <h3>资格校验</h3>
        <ul className="approval-checks">
          {snapshot.eligibilityChecks.map((value) => (
            <li key={value}>{value}</li>
          ))}
        </ul>
      </section>
      <section className="approval-card">
        <p className="queue-kicker">版本化规则</p>
        <h2>政策信息</h2>
        <dl className="approval-facts compact">
          <Fact name="政策版本">{snapshot.policyVersion}</Fact>
          <Fact name="政策层级">{snapshot.policyTier}</Fact>
          <Fact name="提案有效期">{displayTime(snapshot.proposalExpiresAt)}</Fact>
          <Fact name="租约到期">{displayTime(snapshot.leaseExpiresAt)}</Fact>
        </dl>
      </section>
      <section className="approval-card">
        <p className="queue-kicker">最小授权投影</p>
        <h2>证据引用</h2>
        <ul className="approval-evidence">
          {snapshot.evidenceReferences.map((value) => (
            <li key={value}>{value}</li>
          ))}
        </ul>
        <dl className="approval-facts compact">
          {Object.entries(snapshot.evidenceSnapshot).map(([key, value]) => (
            <Fact name={key} key={key}>
              {displayEvidence(value)}
            </Fact>
          ))}
        </dl>
      </section>
      <section className="approval-card approval-chain">
        <p className="queue-kicker">责任边界</p>
        <h2>责任链</h2>
        {snapshot.responsibilityChain.length ? (
          <ol>
            {snapshot.responsibilityChain.map((value, index) => (
              <li key={`${value.eventType}-${index}`}>
                <strong>{value.eventType}</strong>
                <span>
                  {value.actorId} · {displayTime(value.occurredAt)}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="approval-empty">当前投影没有更多责任事件</p>
        )}
      </section>
      <section className="approval-card approval-decisions">
        <p className="queue-kicker">不可逆决定</p>
        <h2>决定操作</h2>
        <p>操作将绑定当前提案版本、内容摘要与审批租约。结果不确定时将恢复 Spring 权威状态。</p>
        <div>
          <button type="button" className="approval-secondary" onClick={() => onAction("release")}>
            释放审批
          </button>
          <button type="button" className="approval-danger" onClick={() => onAction("reject")}>
            驳回并转人工
          </button>
          <button type="button" className="approval-primary" onClick={() => onAction("approve")}>
            批准补偿
          </button>
        </div>
      </section>
    </div>
  );
}

function Fact({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div>
      <dt>{name}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Confirmation({
  action,
  snapshot,
  reason,
  note,
  setReason,
  setNote,
  cancel,
  confirm,
}: {
  action: Exclude<Action, null>;
  snapshot: Snapshot;
  reason: string;
  note: string;
  setReason: (v: string) => void;
  setNote: (v: string) => void;
  cancel: () => void;
  confirm: () => void;
}) {
  const title =
    action === "approve"
      ? "确认批准补偿"
      : action === "reject"
        ? "确认驳回并转人工"
        : "确认释放审批责任";
  return (
    <div className="approval-dialog-backdrop">
      <section className="approval-dialog" role="dialog" aria-modal="true" aria-label={title}>
        <p className="queue-kicker">风险确认</p>
        <h2>{title}</h2>
        <p>
          提案 {shortUuid(snapshot.proposalRevisionId)} · {money(snapshot.authoritativeAmount)}
        </p>
        {action === "reject" ? (
          <label>
            内部驳回理由
            <textarea
              aria-label="内部驳回理由"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
        ) : null}
        {action === "approve" ? (
          <label>
            审批备注（可选）
            <textarea
              aria-label="审批备注（可选）"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
        ) : null}
        <div className="approval-dialog-actions">
          <button type="button" className="approval-secondary" onClick={cancel}>
            取消
          </button>
          <button
            type="button"
            className={action === "approve" ? "approval-primary" : "approval-danger"}
            disabled={action === "reject" && !reason.trim()}
            onClick={confirm}
          >
            {action === "approve" ? "确认批准" : title}
          </button>
        </div>
      </section>
    </div>
  );
}

function leaseHeaders(lease: Lease) {
  return {
    "X-Approval-Lease-Token": lease.leaseToken,
    "X-Approval-Lease-Version": String(lease.leaseVersion),
  };
}
function isQueueItem(v: unknown): v is QueueItem {
  return (
    isRecord(v) &&
    isUuid(v.proposalRevisionId) &&
    typeof v.compensationMethod === "string" &&
    typeof v.amount === "number" &&
    typeof v.submittedAt === "string" &&
    typeof v.expiresAt === "string"
  );
}
function isLease(v: unknown): v is Lease {
  return (
    isRecord(v) &&
    isUuid(v.proposalRevisionId) &&
    isUuid(v.leaseToken) &&
    Number.isSafeInteger(v.leaseVersion) &&
    Number(v.leaseVersion) > 0 &&
    typeof v.expiresAt === "string"
  );
}
function isResponsibility(v: unknown): v is ResponsibilityEvent {
  return (
    isRecord(v) &&
    hasOnlyKeys(v, ["eventType", "actorId", "occurredAt", "leaseVersion"]) &&
    typeof v.eventType === "string" &&
    typeof v.actorId === "string" &&
    typeof v.occurredAt === "string" &&
    (v.leaseVersion === null || typeof v.leaseVersion === "number")
  );
}
function isSnapshot(v: unknown): v is Snapshot {
  const keys = [
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
  ];
  return (
    isRecord(v) &&
    hasOnlyKeys(v, keys) &&
    v.view === "APPROVAL_VIEW" &&
    v.schema === SCHEMA &&
    typeof v.cursor === "string" &&
    parseCursor(v.cursor) !== null &&
    isUuid(v.proposalRevisionId) &&
    Number.isSafeInteger(v.proposalRevision) &&
    typeof v.contentDigest === "string" &&
    typeof v.orderReference === "string" &&
    typeof v.reasonCode === "string" &&
    typeof v.delayHours === "number" &&
    typeof v.delaySeconds === "number" &&
    typeof v.compensationMethod === "string" &&
    typeof v.proposedAmount === "number" &&
    typeof v.authoritativeAmount === "number" &&
    typeof v.policyVersion === "string" &&
    typeof v.policyTier === "string" &&
    Array.isArray(v.eligibilityChecks) &&
    v.eligibilityChecks.every((x) => typeof x === "string") &&
    Array.isArray(v.evidenceReferences) &&
    v.evidenceReferences.every((x) => typeof x === "string") &&
    isRecord(v.evidenceSnapshot) &&
    Array.isArray(v.responsibilityChain) &&
    v.responsibilityChain.every(isResponsibility) &&
    isUuid(v.leaseToken) &&
    Number.isSafeInteger(v.leaseVersion) &&
    typeof v.leaseExpiresAt === "string" &&
    typeof v.submittedAt === "string" &&
    typeof v.proposalExpiresAt === "string"
  );
}
function validEvent(event: SseEvent, lease: Lease, cursor: string) {
  const current = parseCursor(cursor),
    next = parseCursor(event.id);
  if (!current || !next) return false;
  if (next.sequence <= current.sequence) return true;
  if (next.sequence !== current.sequence + 1) return false;
  try {
    const e = JSON.parse(event.data) as unknown;
    return (
      isRecord(e) &&
      hasOnlyKeys(e, ["view", "schema", "payload"]) &&
      e.view === "APPROVAL_VIEW" &&
      e.schema === SCHEMA &&
      isRecord(e.payload) &&
      hasOnlyKeys(e.payload, ["proposalRevisionId", "leaseVersion", "authorityState"]) &&
      event.type === "APPROVAL_AUTHORITY_STARTED" &&
      e.payload.proposalRevisionId === lease.proposalRevisionId &&
      e.payload.leaseVersion === lease.leaseVersion &&
      e.payload.authorityState === "ACTIVE"
    );
  } catch {
    return false;
  }
}
function parseCursor(v: string) {
  return parseViewCursor(v, SCHEMA);
}
function isUuid(v: unknown): v is string {
  return typeof v === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(v);
}
function shortUuid(v: string) {
  return `${v.slice(0, 8)}…${v.slice(-4)}`;
}
function money(v: number) {
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(v);
}
function displayTime(v: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(v),
  );
}
function displayCode(v: string) {
  return v.replaceAll("_", " ");
}
function displayEvidence(v: unknown) {
  return typeof v === "string" || typeof v === "number" || typeof v === "boolean"
    ? String(v)
    : v === null
      ? "—"
      : JSON.stringify(v);
}
