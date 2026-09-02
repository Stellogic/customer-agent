import { describe, expect, it } from "vitest";
import {
  createSupportAssistanceState,
  reduceSupportAssistance,
  type AssistanceRequest,
  type SupportAssignment,
} from "./supportAssistanceState";

// 纯状态 fixture，无 HTTP/模型/检索或真实权限证明。
const assignment: SupportAssignment = {
  sessionKey: "session-a",
  ticketId: "ticket-a",
  assignmentId: "assignment-a",
};
const request: AssistanceRequest = { assignment, requestId: "request-a", kind: "knowledge" };
const initial = createSupportAssistanceState(assignment);
const insufficient = {
  status: "insufficient",
  kind: "knowledge",
  requestId: "request-a",
  explanation: "现有资料不足。",
  followUp: null,
} as const;

describe("HUMAN 辅助 assignment 与请求绑定", () => {
  it("无匹配只是检索中间状态，同请求仍可接受生成的资料不足说明", () => {
    const pending = reduceSupportAssistance(initial, { type: "start", request });
    const noMatch = reduceSupportAssistance(pending, { type: "noMatch", request });
    expect(noMatch.view.status).toBe("empty");
    expect(noMatch.assignment).toEqual(assignment);
    const done = reduceSupportAssistance(noMatch, {
      type: "complete",
      request,
      view: insufficient,
    });
    expect(done.view.status).toBe("insufficient");
    expect(reduceSupportAssistance(done, { type: "noMatch", request })).toBe(done);
  });

  it("迟到无匹配和错误请求身份的资料不足说明不能覆盖当前请求", () => {
    const pending = reduceSupportAssistance(initial, { type: "start", request });
    expect(
      reduceSupportAssistance(pending, {
        type: "noMatch",
        request: { ...request, requestId: "old-request" },
      }),
    ).toBe(pending);
    expect(
      reduceSupportAssistance(pending, {
        type: "complete",
        request,
        view: { ...insufficient, requestId: "wrong-request" },
      }),
    ).toBe(pending);
  });

  it("同参数重试保留请求身份与回执，复用 ID 改类型快速失败", () => {
    const loading = reduceSupportAssistance(initial, { type: "start", request });
    expect(reduceSupportAssistance(loading, { type: "start", request: { ...request } })).toBe(
      loading,
    );
    expect(() =>
      reduceSupportAssistance(loading, { type: "start", request: { ...request, kind: "policy" } }),
    ).toThrow("REQUEST_CONFLICT");
    const done = reduceSupportAssistance(loading, {
      type: "complete",
      request,
      view: insufficient,
    });
    expect(done.request?.requestId).toBe("request-a");
    expect(reduceSupportAssistance(done, { type: "start", request })).toBe(done);
    expect(
      reduceSupportAssistance(done, {
        type: "complete",
        request,
        view: { status: "error", reason: "retrieval" },
      }),
    ).toBe(done);
  });

  it("新请求后忽略同 assignment 旧请求的迟到结果和错误", () => {
    const loading = reduceSupportAssistance(initial, { type: "start", request });
    const newer = { ...request, requestId: "request-b", kind: "policy" } as const;
    const pending = reduceSupportAssistance(loading, { type: "start", request: newer });
    expect(
      reduceSupportAssistance(pending, { type: "complete", request, view: insufficient }),
    ).toBe(pending);
    expect(
      reduceSupportAssistance(pending, {
        type: "complete",
        request,
        view: { status: "error", reason: "retrieval" },
      }),
    ).toBe(pending);
    expect(
      reduceSupportAssistance(pending, {
        type: "complete",
        request: newer,
        view: { ...insufficient, kind: "policy", requestId: "request-b" },
      }).view.status,
    ).toBe("insufficient");
  });

  it("同请求身份不能接受不同辅助类型的内容", () => {
    const loading = reduceSupportAssistance(initial, { type: "start", request });
    expect(
      reduceSupportAssistance(loading, {
        type: "complete",
        request: { ...request, kind: "draft" },
        view: { ...insufficient, kind: "draft" },
      }),
    ).toBe(loading);
    expect(
      reduceSupportAssistance(loading, {
        type: "complete",
        request,
        view: { ...insufficient, kind: "policy", requestId: "request-b" },
      }),
    ).toBe(loading);
  });

  it("撤权清空请求/内容，不接受旧结果，也不再启动请求", () => {
    const loading = reduceSupportAssistance(initial, { type: "start", request });
    const denied = reduceSupportAssistance(loading, { type: "accessDenied", assignment });
    expect(denied).toEqual({ assignment: null, request: null, view: { status: "idle" } });
    expect(reduceSupportAssistance(denied, { type: "complete", request, view: insufficient })).toBe(
      denied,
    );
    expect(reduceSupportAssistance(denied, { type: "start", request })).toBe(denied);
  });

  it("旧请求拒绝仍撤销当前 assignment，但旧 assignment 拒绝不清除新领取", () => {
    const current = reduceSupportAssistance(initial, {
      type: "start",
      request: { ...request, requestId: "new-request" },
    });
    expect(
      reduceSupportAssistance(current, { type: "accessDenied", assignment }).assignment,
    ).toBeNull();
    const nextAssignment = { ...assignment, assignmentId: "assignment-b" };
    const reclaimed = reduceSupportAssistance(current, {
      type: "authorize",
      assignment: nextAssignment,
    });
    expect(reclaimed.request).toBeNull();
    expect(reduceSupportAssistance(reclaimed, { type: "accessDenied", assignment })).toBe(
      reclaimed,
    );
    expect(
      reduceSupportAssistance(reclaimed, { type: "complete", request, view: insufficient }),
    ).toBe(reclaimed);
  });

  it("相同责任快照保留状态，HUMAN 失效/断线通过 null 丢弃状态", () => {
    const loading = reduceSupportAssistance(initial, { type: "start", request });
    expect(
      reduceSupportAssistance(loading, { type: "authorize", assignment: { ...assignment } }),
    ).toBe(loading);
    expect(reduceSupportAssistance(loading, { type: "authorize", assignment: null })).toEqual(
      createSupportAssistanceState(null),
    );
  });
});
