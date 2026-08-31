// #170 自有的客户端展示状态，不是 #169 共用检索 DTO/解析器或服务端授权。
export type AssistanceKind = "summary" | "knowledge" | "policy" | "draft";

export type AssistanceView =
  | { status: "idle" }
  | { status: "loading"; kind: AssistanceKind }
  | { status: "empty"; kind: AssistanceKind }
  | {
      status: "error";
      reason: "conflict" | "index" | "embedding" | "model" | "retrieval" | "request";
    }
  | {
      status: "ready";
      kind: AssistanceKind;
      requestId: string;
      text: string;
      suggestions: string[];
      citations: Array<{
        title: string;
        version: string;
        articleId: string;
        chunkId: string;
        updatedAt: string;
        startLine: number;
        endLine: number;
        snippet: string;
        applicability: string[];
      }>;
    };

// 仅从宿主已验证的 SUPPORT/HUMAN 当前责任投影产生。sessionKey 不是凭据。
export type SupportAssignment = Readonly<{
  sessionKey: string;
  ticketId: string;
  assignmentId: string;
}>;

export type AssistanceRequest = Readonly<{
  assignment: SupportAssignment;
  requestId: string;
  kind: AssistanceKind;
}>;

export type SupportAssistanceState = Readonly<{
  assignment: SupportAssignment | null;
  request: AssistanceRequest | null;
  view: AssistanceView;
}>;

type CompletedView = Exclude<AssistanceView, { status: "idle" | "loading" }>;
export type SupportAssistanceEvent =
  | { type: "authorize"; assignment: SupportAssignment | null }
  | { type: "start"; request: AssistanceRequest }
  | { type: "complete"; request: AssistanceRequest; view: CompletedView }
  | { type: "accessDenied"; assignment: SupportAssignment };

export function assignmentKey(assignment: SupportAssignment): string {
  return JSON.stringify([assignment.sessionKey, assignment.ticketId, assignment.assignmentId]);
}

function sameAssignment(left: SupportAssignment | null, right: SupportAssignment | null) {
  return (
    left === right ||
    (left !== null && right !== null && assignmentKey(left) === assignmentKey(right))
  );
}

export function createSupportAssistanceState(
  assignment: SupportAssignment | null,
): SupportAssistanceState {
  return { assignment, request: null, view: { status: "idle" } };
}

// 无 IO。调用者提供稳定 requestId，重试复用原请求；输入摘要与异参回放由 Spring 校验。
export function reduceSupportAssistance(
  state: SupportAssistanceState,
  event: SupportAssistanceEvent,
): SupportAssistanceState {
  if (event.type === "authorize") {
    return sameAssignment(state.assignment, event.assignment)
      ? state
      : createSupportAssistanceState(event.assignment);
  }
  if (event.type === "accessDenied") {
    return sameAssignment(state.assignment, event.assignment)
      ? createSupportAssistanceState(null)
      : state;
  }
  if (!sameAssignment(state.assignment, event.request.assignment)) return state;
  if (event.type === "start") {
    if (state.request?.requestId === event.request.requestId) {
      // 同 ID 不能改类型，也不能借重试抹掉已经接受的回执。
      if (state.request.kind !== event.request.kind) throw new Error("REQUEST_CONFLICT");
      return state;
    }
    return {
      ...state,
      request: event.request,
      view: { status: "loading", kind: event.request.kind },
    };
  }
  if (
    state.request?.requestId !== event.request.requestId ||
    state.request.kind !== event.request.kind
  )
    return state;
  if (state.view.status !== "loading") return state;
  if ("kind" in event.view && event.view.kind !== event.request.kind) return state;
  if (event.view.status === "ready" && event.view.requestId !== event.request.requestId)
    return state;
  return { ...state, view: event.view };
}
