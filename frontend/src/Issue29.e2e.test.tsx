import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ApprovalWorkbench } from "./ApprovalWorkbench";
import { createCookieBrowserFetch, loginApprover, loginCustomer } from "./liveBrowserTestClient";
import sensitiveContent from "./sensitive-content-patterns.json";

const liveBaseUrl = import.meta.env.VITE_SMOKE_BASE_URL as string | undefined;
const scenario = import.meta.env.VITE_E2E_SCENARIO as "normal" | "reconciliation" | undefined;
const orderReference = import.meta.env.VITE_E2E_ORDER_REFERENCE as string | undefined;
const skipLiveScenario = !liveBaseUrl || !scenario || !orderReference;
const asyncFlowTimeout = 60_000;

function completedSsePayload(payload: string): string {
  const delimiters = [...payload.matchAll(/\r?\n\r?\n/g)];
  const last = delimiters.at(-1);
  return last?.index === undefined ? "" : payload.slice(0, last.index + last[0].length);
}

type AuditedNetworkPayload = {
  direction: "request" | "response";
  path: string;
  payload: string;
};

function normalizeExpectedCsrfResponse(audit: AuditedNetworkPayload): string {
  if (
    audit.direction !== "response" ||
    new URL(audit.path, "http://audit.invalid").pathname !== "/api/auth/csrf"
  ) {
    return audit.payload;
  }
  try {
    const value = JSON.parse(audit.payload) as Record<string, unknown>;
    if (
      Object.keys(value).sort().join(",") !== "headerName,token" ||
      typeof value.token !== "string" ||
      value.headerName !== "X-CSRF-TOKEN"
    ) {
      return audit.payload;
    }
    return JSON.stringify({ token: "<csrf-token>", headerName: value.headerName });
  } catch {
    return audit.payload;
  }
}

describe("Issue #29 网络敏感内容审计", () => {
  it("保留字段审计并归一化预期的随机 CSRF token 值", () => {
    const collidingToken = ["UBS", "K-", "A".repeat(24)].join("");
    const payload = JSON.stringify({ token: collidingToken, headerName: "X-CSRF-TOKEN" });
    const forbidden = new RegExp(
      [...sensitiveContent.contentPatterns, ...sensitiveContent.internalAddressPatterns].join("|"),
      "i",
    );

    expect(payload).toMatch(forbidden);
    const csrfResponse = { direction: "response", path: "/api/auth/csrf", payload } as const;
    expect(normalizeExpectedCsrfResponse(csrfResponse)).toBe(
      '{"token":"<csrf-token>","headerName":"X-CSRF-TOKEN"}',
    );
    expect(normalizeExpectedCsrfResponse(csrfResponse)).not.toMatch(forbidden);
    expect(
      normalizeExpectedCsrfResponse({
        direction: "response",
        path: "/api/other",
        payload,
      }),
    ).toMatch(forbidden);
    expect(
      normalizeExpectedCsrfResponse({
        direction: "response",
        path: "/api/auth/csrf",
        payload: JSON.stringify({
          token: collidingToken,
          headerName: "X-CSRF-TOKEN",
          extra: true,
        }),
      }),
    ).toMatch(forbidden);
    expect(
      normalizeExpectedCsrfResponse({
        direction: "request",
        path: "/api/auth/csrf",
        payload,
      }),
    ).toMatch(forbidden);
    expect(
      normalizeExpectedCsrfResponse({
        direction: "response",
        path: "/api/auth/csrf",
        payload: JSON.stringify({ message: collidingToken }),
      }),
    ).toMatch(forbidden);
  });
});

describe.skipIf(skipLiveScenario)("Issue #29 两条 React 全栈验收", () => {
  const nativeFetch = globalThis.fetch;

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it(`从客户 React 表面贯穿真实 LangGraph、审批 React 表面与模拟执行器：${scenario}`, async () => {
    const browserNetworkPayloads: AuditedNetworkPayload[] = [];
    const streamAudits: Array<{ path: string; payload: string }> = [];
    const browserFetch = createCookieBrowserFetch(nativeFetch, liveBaseUrl ?? "");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path =
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (typeof init?.body === "string") {
        browserNetworkPayloads.push({ direction: "request", path, payload: init.body });
      }
      const response = await browserFetch(path, init);
      if (response.headers.get("content-type")?.includes("text/event-stream") && response.body) {
        const audit = { path, payload: "" };
        streamAudits.push(audit);
        const decoder = new TextDecoder();
        const auditedBody = response.body.pipeThrough(
          new TransformStream<Uint8Array, Uint8Array>({
            transform(chunk, controller) {
              audit.payload += decoder.decode(chunk, { stream: true });
              controller.enqueue(chunk);
            },
            flush() {
              audit.payload += decoder.decode();
            },
          }),
        );
        return new Response(auditedBody, {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers,
        });
      } else {
        browserNetworkPayloads.push({
          direction: "response",
          path,
          payload: await response.clone().text(),
        });
      }
      return response;
    });

    async function approvalQueueRevisionIds(): Promise<string[]> {
      const response = await globalThis.fetch("/api/approver/compensation-proposals", {
        credentials: "same-origin",
      });
      expect(response.ok).toBe(true);
      const queue = (await response.json()) as Array<{ proposalRevisionId: string }>;
      return queue.map((item) => item.proposalRevisionId);
    }

    const approverSession = await loginApprover(globalThis.fetch);
    expect(approverSession.id).toBe("approver-demo");
    const queueBeforeScenario = await approvalQueueRevisionIds();

    const session = await loginCustomer(globalThis.fetch);
    expect(session.id).toBe("customer-demo");
    const customer = render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("订单编号"), { target: { value: orderReference } });
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: `Issue #29 ${scenario} 合成物流延迟验收` },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始智能受理" }));
    expect(
      await screen.findByRole("heading", { name: "请确认我的理解" }, { timeout: 10_000 }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/补偿建议正在等待人工审批/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认，就是这个问题" }));

    expect(
      await screen.findByText(/补偿建议正在等待人工审批/, {}, { timeout: asyncFlowTimeout }),
    ).toBeInTheDocument();
    const ticketUrl = globalThis.location.href;
    customer.unmount();

    expect((await loginApprover(globalThis.fetch)).id).toBe("approver-demo");
    const queueAfterScenario = await approvalQueueRevisionIds();
    const scenarioRevisionIds = queueAfterScenario.filter(
      (revisionId) => !queueBeforeScenario.includes(revisionId),
    );
    expect(scenarioRevisionIds).toHaveLength(1);
    const scenarioQueueIndex = queueAfterScenario.indexOf(scenarioRevisionIds[0]);

    const approver = render(<ApprovalWorkbench />);
    await waitFor(
      () => {
        expect(screen.getAllByRole("button", { name: "领取审批" })).toHaveLength(
          queueAfterScenario.length,
        );
      },
      { timeout: 10_000 },
    );
    fireEvent.click(screen.getAllByRole("button", { name: "领取审批" })[scenarioQueueIndex]);
    expect(await screen.findByRole("heading", { name: orderReference })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "批准补偿" }));
    fireEvent.click(screen.getByRole("button", { name: "确认批准" }));
    expect(
      await screen.findByText("审批责任已结束，已返回队列。", {}, { timeout: 10_000 }),
    ).toBeInTheDocument();
    approver.unmount();

    expect((await loginCustomer(globalThis.fetch)).id).toBe("customer-demo");
    globalThis.history.replaceState(null, "", ticketUrl);
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    if (scenario === "reconciliation") {
      expect(
        await screen.findByText("补偿结果正在自动确认中，请勿重复提交。", {}, { timeout: 10_000 }),
      ).toBeInTheDocument();
    }
    expect(
      await screen.findByText(
        "已完成 26.80 CNY 模拟部分退款，退回原支付方式（尾号 4242）。",
        {},
        { timeout: asyncFlowTimeout },
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText("已解决", {}, { timeout: 10_000 })).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const browserRequests = vi
      .mocked(globalThis.fetch)
      .mock.calls.map(([input]) =>
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url,
      );
    expect(browserRequests.length).toBeGreaterThan(0);
    expect(
      browserRequests.every((request) => {
        const url = new URL(request, liveBaseUrl);
        return (
          url.origin === new URL(liveBaseUrl ?? "http://invalid").origin &&
          url.pathname.startsWith("/api/")
        );
      }),
    ).toBe(true);
    const resolvedByEvent = streamAudits.some((audit) =>
      completedSsePayload(audit.payload).includes("RESOLVED"),
    );
    const resolvedByAuthoritativeSnapshot = browserNetworkPayloads.some((audit) =>
      audit.payload.includes('"lifecycleState":"RESOLVED"'),
    );
    expect(resolvedByEvent || resolvedByAuthoritativeSnapshot).toBe(true);
    const forbiddenNetworkContent = new RegExp(
      [...sensitiveContent.contentPatterns, ...sensitiveContent.internalAddressPatterns].join("|"),
      "i",
    );
    const auditedNetworkContent = [
      ...browserNetworkPayloads.map(normalizeExpectedCsrfResponse),
      ...streamAudits.map((audit) => completedSsePayload(audit.payload)),
    ].join("\n");
    expect(auditedNetworkContent).not.toMatch(forbiddenNetworkContent);
  }, 150_000);
});
