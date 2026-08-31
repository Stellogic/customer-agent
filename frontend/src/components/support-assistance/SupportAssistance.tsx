import { useEffect, useId, useReducer, useRef, useState } from "react";
import { loadCsrfToken } from "../../csrf";
import { humanSessionFetch } from "../../humanSessionLifecycle";
import { isRecord } from "../../streamProtocol";
import { SupportAssistancePanel } from "./SupportAssistancePanel";
import { createSupportAssistanceState, reduceSupportAssistance,
  type AssistanceKind, type AssistanceRequest, type AssistanceView } from "./supportAssistanceState";

const SCHEMA = "support-assistance-v1";

export function SupportAssistance({ ticketId, defaultQuery, onReviewDraft }: {
  ticketId: string;
  defaultQuery: string;
  onReviewDraft: ((text: string) => void) | null;
}) {
  const sessionKey = useId();
  const [state, dispatch] = useReducer(reduceSupportAssistance, null, createSupportAssistanceState);
  const [query, setQuery] = useState(defaultQuery.slice(0, 200));
  const [notice, setNotice] = useState("正在核对人工辅助权限…");
  const [canQuery, setCanQuery] = useState(false);
  const lastRequest = useRef<AssistanceRequest | null>(null);
  const controller = useRef<AbortController | null>(null);
  const url = `/api/support/workbench/tickets/${encodeURIComponent(ticketId)}/assistance`;

  useEffect(() => {
    const active = new AbortController();
    controller.current = active;
    dispatch({ type: "authorize", assignment: null });
    lastRequest.current = null;
    void (async () => {
      try {
        const response = await humanSessionFetch(`${url}/context`, { signal: active.signal,
          credentials: "same-origin", cache: "no-store" });
        if (!response.ok) throw new Error("authority unavailable");
        const value: unknown = await response.json();
        if (!isRecord(value) || value.schema !== SCHEMA || value.ticketId !== ticketId
          || typeof value.assignmentId !== "string") throw new Error("invalid authority");
        if (active.signal.aborted) return;
        dispatch({ type: "authorize", assignment: { sessionKey, ticketId, assignmentId: value.assignmentId } });
        setNotice("");
      } catch {
        if (!active.signal.aborted) setNotice("辅助权限不可用；人工处理可继续，重新打开详情后重试。");
      }
    })();
    return () => active.abort();
  }, [sessionKey, ticketId, url]);

  async function acceptResponse(response: Response, request: AssistanceRequest, signal: AbortSignal) {
    if (signal.aborted) return;
    if ([401, 403, 404].includes(response.status)) {
      dispatch({ type: "accessDenied", assignment: request.assignment });
      setNotice("辅助授权已失效，内容与草稿已清除。");
      return;
    }
    if (!response.ok) {
      const value: unknown = await response.json();
      const code = isRecord(value) ? value.code : null;
      const reason = code === "INDEX_STALE" ? "index" : code === "MODEL_UNAVAILABLE" ? "embedding"
        : response.status === 422 ? "conflict" : [400, 409].includes(response.status) ? "request" : "retrieval";
      if (!signal.aborted) dispatch({ type: "complete", request, view: { status: "error", reason } });
      return;
    }
    const value: unknown = await response.json();
    const view = decodeAssistanceResponse(value, request);
    if (signal.aborted) return;
    if (view.status === "loading") {
      setCanQuery(true);
      setNotice("请求尚无终态回执，可查询同一请求；不会再次调用模型。");
    } else if (view.status !== "idle" && view.status !== "empty") {
      dispatch({ type: "complete", request, view });
      setNotice("");
    }
  }

  async function start(kind: AssistanceKind) {
    const active = controller.current;
    if (!state.assignment || !active || active.signal.aborted || !query.trim()) return;
    const request = { assignment: state.assignment, requestId: crypto.randomUUID(), kind };
    lastRequest.current = request;
    dispatch({ type: "start", request });
    setNotice("");
    setCanQuery(false);
    let csrf;
    try {
      csrf = await loadCsrfToken();
    } catch {
      if (!active.signal.aborted) {
        dispatch({ type: "complete", request, view: { status: "error", reason: "request" } });
        setNotice("发送凭证不可用，尚未发起辅助请求。");
      }
      return;
    }
    try {
      if (active.signal.aborted) return;
      const response = await humanSessionFetch(`${url}/requests`, { method: "POST", signal: active.signal,
        credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json", [csrf.headerName]: csrf.token },
        body: JSON.stringify({ schema: SCHEMA, assignmentId: request.assignment.assignmentId,
          requestId: request.requestId, kind, query: query.trim() }) });
      await acceptResponse(response, request, active.signal);
    } catch {
      if (!active.signal.aborted) {
        setCanQuery(true);
        setNotice("暂未确认辅助结果，请查询原请求；不会自动重复调用模型。");
      }
    }
  }

  async function queryResult() {
    const request = lastRequest.current;
    const active = controller.current;
    if (!request || !active || active.signal.aborted) return;
    try {
      const response = await humanSessionFetch(`${url}/requests/${request.requestId}`, {
        signal: active.signal, credentials: "same-origin", cache: "no-store" });
      await acceptResponse(response, request, active.signal);
    } catch {
      if (!active.signal.aborted) setNotice("仍未确认辅助结果，请稍后查询；人工编辑可继续。");
    }
  }

  return <div className="support-assistance-host">
    {state.assignment && <label>辅助查询（最多200字）
      <textarea value={query} maxLength={200} rows={2} onChange={(event) => setQuery(event.target.value)} />
    </label>}
    <SupportAssistancePanel state={state} onReviewDraft={onReviewDraft}
      onRequest={query.trim() ? (kind) => void start(kind) : null} />
    {state.assignment && state.view.status === "loading" && canQuery && lastRequest.current &&
      <button type="button" onClick={() => void queryResult()}>查询辅助结果</button>}
    {notice && <p role="status">{notice}</p>}
  </div>;
}

/** 仅解码170浏览器投影；不是共享检索DTO或其替代解析器。 */
export function decodeAssistanceResponse(value: unknown, request: AssistanceRequest): AssistanceView {
  if (!isRecord(value) || value.schema !== SCHEMA || value.ticketId !== request.assignment.ticketId
    || value.assignmentId !== request.assignment.assignmentId || value.requestId !== request.requestId
    || value.kind !== request.kind || !isRecord(value.view)) throw new Error("invalid assistance response");
  const view = value.view;
  if (view.status === "loading" && view.kind === request.kind) return { status: "loading", kind: request.kind };
  if (view.status === "error" && ["conflict", "index", "embedding", "model", "retrieval", "request", "format"].includes(String(view.reason)))
    return { status: "error", reason: view.reason as Extract<AssistanceView, { status: "error" }>["reason"] };
  if (view.kind !== request.kind || view.requestId !== request.requestId) throw new Error("wrong assistance identity");
  if (view.status === "insufficient" && typeof view.explanation === "string"
    && (view.followUp === null || typeof view.followUp === "string"))
    return { status: "insufficient", kind: request.kind, requestId: request.requestId,
      explanation: view.explanation, followUp: view.followUp };
  if (view.status === "ready" && typeof view.text === "string" && Array.isArray(view.suggestions)
    && view.suggestions.every((item) => typeof item === "string") && Array.isArray(view.citations)
    && view.citations.every((item) => isRecord(item)
      && ["articleId", "version", "chunkId", "title", "updatedAt", "snippet"].every((key) => typeof item[key] === "string")
      && typeof item.startLine === "number" && typeof item.endLine === "number"
      && Array.isArray(item.applicability) && item.applicability.every((scope) => typeof scope === "string"))) {
    return { status: "ready", kind: request.kind, requestId: request.requestId, text: view.text,
      suggestions: view.suggestions, citations: view.citations as Extract<AssistanceView, { status: "ready" }>["citations"] };
  }
  throw new Error("invalid assistance view");
}
