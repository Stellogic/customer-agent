import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

describe.skipIf(skipLiveScenario)("Issue #29 两条 React 全栈验收", () => {
  const nativeFetch = globalThis.fetch;

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it(`从客户 React 表面贯穿真实 LangGraph、审批 React 表面与模拟执行器：${scenario}`, async () => {
    const browserNetworkPayloads: string[] = [];
    const streamAudits: Array<{ payload: string }> = [];
    const browserFetch = createCookieBrowserFetch(nativeFetch, liveBaseUrl ?? "");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path =
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (typeof init?.body === "string") {
        browserNetworkPayloads.push(init.body);
      }
      const response = await browserFetch(path, init);
      if (response.headers.get("content-type")?.includes("text/event-stream") && response.body) {
        const audit = { payload: "" };
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
        browserNetworkPayloads.push(await response.clone().text());
      }
      return response;
    });

    async function approvalQueueRevisionIds(): Promise<string[]> {
      const response = await globalThis.fetch("/api/approver/compensation-proposals", {
        headers: { "X-Synthetic-Approver-Id": "approver-demo" },
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
    const customer = render(<App />);
    fireEvent.change(screen.getByLabelText("订单编号"), { target: { value: orderReference } });
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: `Issue #29 ${scenario} 合成物流延迟验收` },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交物流延迟问题" }));

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

    const approver = render(<ApprovalWorkbench approverId="approver-demo" />);
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
    expect(
      await screen.findByText("审批责任已结束，已返回队列。", {}, { timeout: 10_000 }),
    ).toBeInTheDocument();
    approver.unmount();

    expect((await loginCustomer(globalThis.fetch)).id).toBe("customer-demo");
    globalThis.history.replaceState(null, "", ticketUrl);
    render(<App />);
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
    expect(await screen.findByText("RESOLVED", {}, { timeout: 10_000 })).toBeInTheDocument();
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
    await waitFor(
      () => {
        expect(
          streamAudits.some((audit) => completedSsePayload(audit.payload).includes("RESOLVED")),
        ).toBe(true);
      },
      { timeout: 5_000 },
    );
    const forbiddenNetworkContent = new RegExp(
      [...sensitiveContent.contentPatterns, ...sensitiveContent.internalAddressPatterns].join("|"),
      "i",
    );
    const auditedNetworkContent = [
      ...browserNetworkPayloads,
      ...streamAudits.map((audit) => completedSsePayload(audit.payload)),
    ].join("\n");
    expect(auditedNetworkContent).not.toMatch(forbiddenNetworkContent);
  }, 150_000);
});
