import { ConfigProvider } from "antd";
import type { ReactElement } from "react";
import {
  cleanup,
  fireEvent,
  render as rtlRender,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SupportWorkbench } from "./SupportWorkbench";
import { ApprovalWorkbench } from "./ApprovalWorkbench";
import { resetHumanSessionLifecycleForTests } from "./humanSessionLifecycle";

// 本票只验证入口与宿主的连接；标准补偿仍由 #164 的测试覆盖。
vi.mock("./SupportCompensationPanel", () => ({ SupportCompensationPanel: () => null }));
vi.mock("./components/support-assistance/SupportAssistance", () => ({
  SupportAssistance: () => <div>合成辅助宿主</div>,
}));

const ticketId = "19300000-0000-0000-0000-000000000001";
const revisionId = "19300000-0000-0000-0000-000000000002";
const leaseToken = "19300000-0000-0000-0000-000000000003";
const supportSnapshotUrl = "/api/support/workbench/snapshot?schema=support-workbench-v2";
const supportDetailUrl = `/api/support/workbench/tickets/${ticketId}`;
const approvalQueueUrl = "/api/approver/compensation-proposals";

// jsdom 不执行 CSS 动画；只在本票测试中关闭 motion，保留真实弹层和关闭断言。
function render(ui: ReactElement) {
  return rtlRender(ui, {
    wrapper: ({ children }) => (
      <ConfigProvider theme={{ token: { motion: false } }}>{children}</ConfigProvider>
    ),
  });
}
afterEach(() => {
  cleanup();
  resetHumanSessionLifecycleForTests();
  vi.restoreAllMocks();
  sessionStorage.clear();
  history.replaceState(null, "", "/");
});

function openStream() {
  return new Response(new ReadableStream<Uint8Array>(), {
    headers: { "Content-Type": "text/event-stream" },
  });
}

function supportSnapshot() {
  return Response.json({
    view: "SUPPORT_WORKBENCH",
    schema: "support-workbench-v2",
    cursor: "support-workbench-v2:1",
    sharedQueue: [],
    escalationQueue: [],
    assignedTicketIds: [ticketId],
  });
}

function supportDetail(handlingMode = "HUMAN") {
  return Response.json({
    ticketId,
    customerId: "customer-fixture",
    orderReference: "ORDER-193",
    description: "物流延迟",
    lifecycleState: "WAITING_FOR_CUSTOMER",
    handlingMode,
    assignedSupportId: "support-fixture",
    publicConversation: [],
    businessTimeline: [],
    investigationFacts: [
      {
        factType: "DELIVERY_DELAY",
        factValue: "26 hours",
        evidenceReference: "shipment:ORDER-193",
        recordedAt: "2026-08-31T01:00:00Z",
      },
    ],
  });
}

describe("#193 现有授权工作台入口接线", () => {
  it("客服恢复已领取详情后定位现有内容；同步和撤权移除入口及弹层", async () => {
    let snapshotReads = 0;
    let resolveSnapshot: (response: Response) => void = () => undefined;
    let closeAuthority: () => void = () => undefined;
    let authorized = true;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === supportSnapshotUrl) {
        snapshotReads += 1;
        if (snapshotReads === 2)
          return new Promise<Response>((resolve) => {
            resolveSnapshot = resolve;
          });
        return supportSnapshot();
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === supportDetailUrl)
        return authorized ? supportDetail() : new Response(null, { status: 403 });
      if (path === `${supportDetailUrl}/events`) {
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              closeAuthority = () => controller.close();
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      }
      throw new Error(`unexpected request: ${path}`);
    });
    render(<SupportWorkbench />);
    const entries = await screen.findByRole("region", { name: "客服详情入口" });
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url === `${supportDetailUrl}/events`)).toBe(true),
    );
    const before = fetchMock.mock.calls.length;
    fireEvent.click(within(entries).getByRole("button", { name: "查看订单" }));
    expect(document.activeElement).toHaveTextContent("ORDER-193");
    fireEvent.click(within(entries).getByRole("button", { name: "查看物流" }));
    expect(screen.getByRole("region", { name: "调查事实" })).toHaveFocus();
    fireEvent.click(within(entries).getByRole("button", { name: "联系客户" }));
    expect(screen.getByRole("region", { name: "人工公开回复" })).toHaveFocus();
    expect(screen.getByRole("textbox", { name: "公开回复" })).toHaveValue("");
    for (const label of ["建议动作", "相似案例"]) {
      fireEvent.click(within(entries).getByRole("button", { name: label }));
      expect(screen.getByRole("region", { name: "AI 智能辅助" })).toHaveFocus();
    }
    fireEvent.click(within(entries).getByRole("button", { name: "转派" }));
    await screen.findByRole("dialog", { name: "转派 · 开发中" });
    expect(fetchMock).toHaveBeenCalledTimes(before);

    // 宿主同步路径清详情，不只验证独立组件的 null props。
    fireEvent.click(screen.getByRole("button", { name: "重新同步队列" }));
    expect(screen.queryByRole("region", { name: "客服详情入口" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    resolveSnapshot(supportSnapshot());
    const restored = await screen.findByRole("region", { name: "客服详情入口" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(within(restored).getByRole("button", { name: "更多操作" }));
    await screen.findByRole("dialog", { name: "更多操作 · 开发中" });
    authorized = false;
    closeAuthority();
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "客服详情入口" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("ORDER-193")).not.toBeInTheDocument();
  });

  it("非 HUMAN 的授权详情不通过联系客户入口开放回复", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === supportSnapshotUrl) return supportSnapshot();
      if (path === supportDetailUrl) return supportDetail("AGENT");
      if (path.endsWith("/events")) return openStream();
      throw new Error(`unexpected request: ${path}`);
    });
    render(<SupportWorkbench />);
    const entries = await screen.findByRole("region", { name: "客服详情入口" });
    expect(within(entries).getByRole("button", { name: "联系客户" })).toBeDisabled();
    expect(screen.queryByRole("textbox", { name: "公开回复" })).not.toBeInTheDocument();
  });

  // 每项独立挂载，避免 rc util 测试模式的固定标题 ID 在保留弹层间冲突。
  it.each(["更多筛选", "导出"])("审批 %s 无请求，详情入口随撤权卸载", async (label) => {
    let closeAuthority: () => void = () => undefined;
    let authorized = true;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/auth/csrf")
        return Response.json({ token: "fixture", headerName: "X-CSRF-TOKEN" });
      if (path === approvalQueueUrl)
        return Response.json([
          {
            proposalRevisionId: revisionId,
            compensationMethod: "COUPON",
            amount: 20,
            submittedAt: "2026-08-31T01:00:00Z",
            expiresAt: "2099-01-01T00:00:00Z",
          },
        ]);
      if (path.endsWith("/claims"))
        return Response.json({
          proposalRevisionId: revisionId,
          leaseToken,
          leaseVersion: 1,
          expiresAt: "2099-01-01T00:00:00Z",
        });
      if (path.endsWith("/approval-view"))
        return authorized ? Response.json(approvalSnapshot()) : new Response(null, { status: 403 });
      if (path.endsWith("/events"))
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              closeAuthority = () => controller.close();
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      throw new Error(`unexpected request: ${path}`);
    });
    render(<ApprovalWorkbench />);
    await screen.findByRole("button", { name: "领取审批" });
    expect(screen.queryByRole("region", { name: "审批详情入口" })).not.toBeInTheDocument();
    const queueReads = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: label }));
    const dialog = await screen.findByRole("dialog", { name: `${label} · 开发中` });
    fireEvent.click(within(dialog).getByRole("button", { name: "知道了" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(queueReads);
    fireEvent.click(screen.getByRole("button", { name: "领取审批" }));
    const entries = await screen.findByRole("region", { name: "审批详情入口" });
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/events"))).toBe(true),
    );
    const before = fetchMock.mock.calls.length;
    for (const [label, target] of [
      ["政策详情", "政策信息"],
      ["提案日志", "责任链"],
      ["资格检查明细", "资格与金额"],
    ]) {
      fireEvent.click(within(entries).getByRole("button", { name: label }));
      expect(screen.getByRole("region", { name: target })).toHaveFocus();
    }
    fireEvent.click(within(entries).getByRole("button", { name: "物流轨迹" }));
    expect(document.activeElement).toHaveTextContent("80 小时（288000 秒）");
    expect(within(entries).getByRole("button", { name: "完整对话" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(before);
    authorized = false;
    closeAuthority();
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "审批详情入口" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByText("delay-policy-v1")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "批准补偿" })).not.toBeInTheDocument();
  });
});

function approvalSnapshot() {
  return {
    view: "APPROVAL_VIEW",
    schema: "approval-view-v1",
    cursor: "approval-view-v1:1",
    proposalRevisionId: revisionId,
    proposalRevision: 1,
    contentDigest: "0".repeat(64),
    orderReference: "ORDER-193",
    reasonCode: "LOGISTICS_DELAY",
    delayHours: 80,
    delaySeconds: 288000,
    compensationMethod: "COUPON",
    proposedAmount: 20,
    authoritativeAmount: 20,
    policyVersion: "delay-policy-v1",
    policyTier: "OVER_72_HOURS",
    eligibilityChecks: ["ORDER_PAID"],
    evidenceReferences: ["shipment:ORDER-193"],
    evidenceSnapshot: { delayHours: 80 },
    responsibilityChain: [],
    leaseToken,
    leaseVersion: 1,
    leaseExpiresAt: "2099-01-01T00:00:00Z",
    submittedAt: "2026-08-31T01:00:00Z",
    proposalExpiresAt: "2099-01-01T00:00:00Z",
  };
}
