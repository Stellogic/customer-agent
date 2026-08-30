import { useEffect, useState } from "react";
import { loadCsrfToken } from "./csrf";
import { humanSessionFetch } from "./humanSessionLifecycle";
import { hasOnlyKeys, isRecord } from "./streamProtocol";
import type { PendingCompensationBody } from "./supportCompensationStorage";
import {
  clearPendingCompensationSubmit,
  readPendingCompensationSubmit,
  storePendingCompensationSubmit,
} from "./supportCompensationStorage";

const SUPPORT_SCHEMA = "support-workbench-v2" as const;

type CompensationPlan = {
  planCode: string;
  compensationMethod: string;
  amount: string;
  capAmount: string;
  currency: string;
  reasonCodes: string[];
};

type CompensationOptions = {
  schema: typeof SUPPORT_SCHEMA;
  policyVersion: string;
  plans: CompensationPlan[];
};

class CompensationUncertainError extends Error {}

class CompensationRejectedError extends Error {}

export function SupportCompensationPanel({
  ticketId,
  handlingMode,
  onSubmitted,
}: {
  ticketId: string;
  handlingMode: "AGENT" | "HUMAN";
  onSubmitted: () => void;
}) {
  const stored = handlingMode === "HUMAN" ? readPendingCompensationSubmit(ticketId) : null;
  const [optionsState, setOptionsState] = useState<"loading" | "ready" | "error">("loading");
  const [options, setOptions] = useState<CompensationOptions | null>(null);
  const [planCode, setPlanCode] = useState("");
  const [reasonCode, setReasonCode] = useState("LOGISTICS_DELAY");
  const [justification, setJustification] = useState("");
  const [submitState, setSubmitState] = useState<"idle" | "submitting" | "unknown" | "error">(
    stored ? "unknown" : "idle",
  );
  const [pendingKind, setPendingKind] = useState<"proposal" | "exception" | null>(
    stored?.kind ?? null,
  );
  const [pendingKey, setPendingKey] = useState(stored?.idempotencyKey ?? "");
  const [pendingBody, setPendingBody] = useState<PendingCompensationBody | null>(
    stored?.body ?? null,
  );
  const [notice, setNotice] = useState(
    stored ? "上次标准补偿提交结果尚未确认，请查询 Spring 权威结果。" : "",
  );

  useEffect(() => {
    if (handlingMode !== "HUMAN") return;
    const controller = new AbortController();
    void loadOptions(ticketId, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      if (!value) {
        setOptions(null);
        setOptionsState("error");
        return;
      }
      setOptions(value);
      setPlanCode(value.plans[0]?.planCode ?? "");
      setReasonCode(value.plans[0]?.reasonCodes[0] ?? "LOGISTICS_DELAY");
      setOptionsState("ready");
    });
    return () => controller.abort();
  }, [ticketId, handlingMode]);

  if (handlingMode !== "HUMAN") return null;

  const selected = options?.plans.find((plan) => plan.planCode === planCode) ?? null;
  const busy = submitState === "submitting" || submitState === "unknown";
  const canSubmitException = optionsState === "ready" && options?.plans.length === 0;

  async function submitProposal() {
    if (!selected) return;
    const idempotencyKey = globalThis.crypto.randomUUID();
    const body = {
      schema: SUPPORT_SCHEMA,
      planCode: selected.planCode,
      reasonCode,
    };
    setPendingKind("proposal");
    setPendingKey(idempotencyKey);
    setPendingBody(body);
    storePendingCompensationSubmit(ticketId, { kind: "proposal", idempotencyKey, body });
    setSubmitState("submitting");
    setNotice("");
    try {
      await postCompensation(
        `/api/support/workbench/tickets/${ticketId}/compensation-proposals`,
        idempotencyKey,
        body,
        ticketId,
        "proposal",
      );
      clearPendingCompensationSubmit(ticketId);
      setSubmitState("idle");
      setNotice("标准补偿提案已提交审批。客户只会看到类型、金额和待审批。");
      onSubmitted();
    } catch (error) {
      if (error instanceof CompensationUncertainError) {
        setSubmitState("unknown");
        setNotice(error.message);
        return;
      }
      clearPendingCompensationSubmit(ticketId);
      setSubmitState("error");
      setNotice(error instanceof Error ? error.message : "标准补偿提交未被接受。");
    }
  }

  async function submitException() {
    const idempotencyKey = globalThis.crypto.randomUUID();
    const body: PendingCompensationBody = {
      schema: SUPPORT_SCHEMA,
      reasonCode: "STANDARD_PLAN_INSUFFICIENT",
      justification: justification.trim(),
    };
    setPendingKind("exception");
    setPendingKey(idempotencyKey);
    setPendingBody(body);
    storePendingCompensationSubmit(ticketId, { kind: "exception", idempotencyKey, body });
    setSubmitState("submitting");
    setNotice("");
    try {
      await postCompensation(
        `/api/support/workbench/tickets/${ticketId}/exceptional-compensation-requests`,
        idempotencyKey,
        body,
        ticketId,
        "exception",
      );
      clearPendingCompensationSubmit(ticketId);
      setJustification("");
      setSubmitState("idle");
      setNotice("例外补偿申请已提交，不会走普通提案审批捷径。");
      onSubmitted();
    } catch (error) {
      if (error instanceof CompensationUncertainError) {
        setSubmitState("unknown");
        setNotice(error.message);
        return;
      }
      clearPendingCompensationSubmit(ticketId);
      setSubmitState("error");
      setNotice(error instanceof Error ? error.message : "例外补偿申请未被接受。");
    }
  }

  async function retryPendingSubmit() {
    if (!pendingKind || !pendingKey || !pendingBody || submitState === "submitting") return;
    const path =
      pendingKind === "proposal"
        ? `/api/support/workbench/tickets/${ticketId}/compensation-proposals`
        : `/api/support/workbench/tickets/${ticketId}/exceptional-compensation-requests`;
    setSubmitState("submitting");
    setNotice("正在使用同一请求身份重试提交…");
    try {
      await postCompensation(path, pendingKey, pendingBody, ticketId, pendingKind);
      clearPendingCompensationSubmit(ticketId);
      setSubmitState("idle");
      setNotice(
        pendingKind === "proposal"
          ? "标准补偿提案已提交审批。客户只会看到类型、金额和待审批。"
          : "例外补偿申请已提交，不会走普通提案审批捷径。",
      );
      onSubmitted();
    } catch (error) {
      if (error instanceof CompensationUncertainError) {
        setSubmitState("unknown");
        setNotice(error.message);
        return;
      }
      clearPendingCompensationSubmit(ticketId);
      setSubmitState("error");
      setNotice(
        error instanceof Error ? error.message : "补偿提交未被接受。请确认当前客服责任后重试。",
      );
    }
  }

  async function queryResult() {
    if (!pendingKind || !pendingKey || submitState === "submitting") return;
    const path =
      pendingKind === "proposal"
        ? `/api/support/workbench/tickets/${ticketId}/compensation-proposals/${pendingKey}`
        : `/api/support/workbench/tickets/${ticketId}/exceptional-compensation-requests/${pendingKey}`;
    setSubmitState("submitting");
    try {
      const response = await humanSessionFetch(path, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (response.status === 404) {
        setSubmitState("unknown");
        setNotice("Spring 尚未找到该提交请求，请稍后使用同一请求身份继续查询。");
        return;
      }
      if (!response.ok) throw new Error("query failed");
      const value = (await response.json()) as unknown;
      const valid =
        pendingKind === "proposal"
          ? isConfirmedProposalResult(value, ticketId, pendingKey)
          : isConfirmedExceptionResult(value, ticketId, pendingKey);
      if (!valid) throw new Error("invalid query result");
      clearPendingCompensationSubmit(ticketId);
      setSubmitState("idle");
      setNotice(
        pendingKind === "proposal"
          ? "已从 Spring 权威结果确认标准补偿提案已提交审批。"
          : "已从 Spring 权威结果确认例外补偿申请已保存。",
      );
      onSubmitted();
    } catch {
      setSubmitState("unknown");
      setNotice("提交结果仍未确认；请继续查询 Spring 权威结果，不要重复提交。");
    }
  }

  return (
    <section className="support-compensation-panel" aria-labelledby="support-compensation-title">
      <div className="support-reply-heading">
        <div>
          <p className="eyebrow">SPRING 权威方案</p>
          <h3 id="support-compensation-title">标准补偿</h3>
        </div>
        <span>金额与方式由政策计算</span>
      </div>
      {optionsState === "loading" && (
        <p className="support-compensation-status" role="status">
          正在读取当前允许的标准补偿方案…
        </p>
      )}
      {optionsState === "error" && (
        <p className="error" role="alert">
          标准补偿方案暂时不可用，请重新同步后再试。
        </p>
      )}
      {optionsState === "ready" && options && options.plans.length === 0 && (
        <p className="support-compensation-empty">当前没有允许的标准补偿方案。</p>
      )}
      {optionsState === "ready" && selected && (
        <form
          className="support-compensation-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submitProposal();
          }}
        >
          <label>
            补偿方案
            <select
              aria-label="补偿方案"
              value={planCode}
              disabled={busy}
              onChange={(event) => setPlanCode(event.target.value)}
            >
              {options?.plans.map((plan) => (
                <option key={plan.planCode} value={plan.planCode}>
                  {methodLabel(plan.compensationMethod)} · {plan.amount} {plan.currency}
                </option>
              ))}
            </select>
          </label>
          <dl className="support-compensation-facts">
            <div>
              <dt>资格金额</dt>
              <dd>
                {selected.amount} {selected.currency}
              </dd>
            </div>
            <div>
              <dt>政策上限</dt>
              <dd>
                {selected.capAmount} {selected.currency}
              </dd>
            </div>
            <div>
              <dt>政策版本</dt>
              <dd>{options?.policyVersion}</dd>
            </div>
          </dl>
          <label>
            受控理由
            <select
              aria-label="受控理由"
              value={reasonCode}
              disabled={busy}
              onChange={(event) => setReasonCode(event.target.value)}
            >
              {selected.reasonCodes.map((code) => (
                <option key={code} value={code}>
                  {reasonLabel(code)}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={busy || !planCode}>
            {submitState === "submitting" && pendingKind === "proposal"
              ? "正在提交审批…"
              : "提交审批"}
          </button>
        </form>
      )}
      {canSubmitException && (
        <form
          className="support-exception-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submitException();
          }}
        >
          <p className="eyebrow">例外补偿申请</p>
          <p>超出标准方案时走独立审查，不能改写普通提案金额。</p>
          <label>
            申请说明
            <textarea
              aria-label="例外补偿说明"
              value={justification}
              maxLength={2000}
              disabled={busy}
              onChange={(event) => setJustification(event.target.value)}
              placeholder="说明标准方案为何不足…"
              rows={3}
            />
          </label>
          <button type="submit" disabled={busy || !justification.trim()}>
            {submitState === "submitting" && pendingKind === "exception"
              ? "正在提交例外申请…"
              : "提交例外补偿申请"}
          </button>
        </form>
      )}
      {submitState === "unknown" && pendingKey && (
        <div className="support-compensation-recovery-actions">
          <button type="button" className="support-reply-query" onClick={() => void queryResult()}>
            查询提交结果
          </button>
          {pendingBody && (
            <button
              type="button"
              className="support-reply-query"
              onClick={() => void retryPendingSubmit()}
            >
              使用同一请求身份重试提交
            </button>
          )}
        </div>
      )}
      {notice && (
        <p
          className={submitState === "error" ? "error" : "support-reply-notice"}
          role={submitState === "error" || submitState === "unknown" ? "alert" : "status"}
        >
          {notice}
        </p>
      )}
    </section>
  );
}

async function loadOptions(ticketId: string, signal: AbortSignal) {
  try {
    const response = await humanSessionFetch(
      `/api/support/workbench/tickets/${ticketId}/compensation-options`,
      { credentials: "same-origin", cache: "no-store", signal },
    );
    if (!response.ok) return null;
    const value = (await response.json()) as unknown;
    return isOptions(value) ? value : null;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return null;
    return null;
  }
}

async function postCompensation(
  path: string,
  idempotencyKey: string,
  body: Record<string, string>,
  ticketId: string,
  kind: "proposal" | "exception",
) {
  let csrf: Awaited<ReturnType<typeof loadCsrfToken>>;
  try {
    csrf = await loadCsrfToken();
  } catch {
    throw new CompensationRejectedError("无法取得提交凭证，请稍后重试。");
  }
  let response: Response;
  try {
    response = await humanSessionFetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        [csrf.headerName]: csrf.token,
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new CompensationUncertainError(
      "提交结果暂未确认；请查询 Spring 权威结果，不要重复提交。",
    );
  }
  if (!response.ok && response.status < 500) {
    throw new CompensationRejectedError(
      response.status === 400
        ? "不能覆盖金额或方式，请重新选择标准方案。"
        : "提交未被接受，请确认当前客服责任后重试。",
    );
  }
  if (!response.ok) {
    throw new CompensationUncertainError(
      "提交结果暂未确认；请查询 Spring 权威结果，不要重复提交。",
    );
  }
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new CompensationUncertainError(
      "提交结果暂未确认；请查询 Spring 权威结果，不要重复提交。",
    );
  }
  const valid =
    kind === "proposal"
      ? isConfirmedProposalResult(value, ticketId, idempotencyKey, false)
      : isConfirmedExceptionResult(value, ticketId, idempotencyKey, false);
  if (!valid) {
    throw new CompensationUncertainError(
      "提交结果暂未确认；请查询 Spring 权威结果，不要重复提交。",
    );
  }
}

function isOptions(value: unknown): value is CompensationOptions {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ["schema", "policyVersion", "plans"]) ||
    value.schema !== SUPPORT_SCHEMA ||
    typeof value.policyVersion !== "string" ||
    !Array.isArray(value.plans)
  )
    return false;
  const plans = value.plans.map(normalizePlan);
  if (plans.some((plan) => plan === null)) return false;
  value.plans = plans.filter((plan): plan is CompensationPlan => plan !== null);
  return true;
}

function isConfirmedProposalResult(
  value: unknown,
  ticketId: string,
  requestId: string,
  requireReplayed = true,
) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "schema",
      "ticketId",
      "requestId",
      "proposalRevisionId",
      "proposalRevision",
      "compensationMethod",
      "amount",
      "currency",
      "status",
      "outcome",
      "replayed",
    ]) &&
    value.schema === SUPPORT_SCHEMA &&
    value.ticketId === ticketId &&
    value.requestId === requestId &&
    isUuid(value.proposalRevisionId) &&
    typeof value.proposalRevision === "number" &&
    Number.isInteger(value.proposalRevision) &&
    value.proposalRevision > 0 &&
    typeof value.compensationMethod === "string" &&
    typeof value.amount === "number" &&
    Number.isFinite(value.amount) &&
    value.amount >= 0 &&
    value.currency === "CNY" &&
    value.status === "PENDING_APPROVAL" &&
    value.outcome === "ACCEPTED" &&
    typeof value.replayed === "boolean" &&
    (!requireReplayed || value.replayed === true)
  );
}

function isConfirmedExceptionResult(
  value: unknown,
  ticketId: string,
  requestId: string,
  requireReplayed = true,
) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "schema",
      "ticketId",
      "requestId",
      "exceptionalRequestId",
      "reasonCode",
      "status",
      "outcome",
      "replayed",
    ]) &&
    value.schema === SUPPORT_SCHEMA &&
    value.ticketId === ticketId &&
    value.requestId === requestId &&
    isUuid(value.exceptionalRequestId) &&
    value.reasonCode === "STANDARD_PLAN_INSUFFICIENT" &&
    value.status === "SUBMITTED" &&
    value.outcome === "ACCEPTED" &&
    typeof value.replayed === "boolean" &&
    (!requireReplayed || value.replayed === true)
  );
}

function isUuid(value: unknown) {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
  );
}

function normalizePlan(value: unknown): CompensationPlan | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "planCode",
      "compensationMethod",
      "amount",
      "capAmount",
      "currency",
      "reasonCodes",
    ])
  )
    return null;
  const amount = moneyText(value.amount);
  const capAmount = moneyText(value.capAmount);
  if (
    typeof value.planCode !== "string" ||
    typeof value.compensationMethod !== "string" ||
    amount === null ||
    capAmount === null ||
    value.currency !== "CNY" ||
    !Array.isArray(value.reasonCodes) ||
    value.reasonCodes.some((code) => typeof code !== "string")
  )
    return null;
  return {
    planCode: value.planCode,
    compensationMethod: value.compensationMethod,
    amount,
    capAmount,
    currency: value.currency,
    reasonCodes: value.reasonCodes.filter((code): code is string => typeof code === "string"),
  };
}

function moneyText(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value.toFixed(2);
  if (typeof value === "string" && /^\d+\.\d{2}$/.test(value)) return value;
  return null;
}

function methodLabel(method: string) {
  return method === "COUPON" ? "优惠券" : "模拟原路部分退款";
}

function reasonLabel(code: string) {
  return code === "LOGISTICS_DELAY" ? "物流延迟" : code;
}
