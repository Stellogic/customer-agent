import { useEffect, useState } from "react";
import { StatusNotice } from "./components/SystemState";
import { humanSessionFetch } from "./humanSessionLifecycle";
import { hasOnlyKeys, isRecord } from "./streamProtocol";

const SCHEMA = "customer-order-ticket-groups-v1" as const;

type TicketSummary = {
  ticketId: string;
  issueKind: string;
  lifecycleState: string;
  handlingMode: string;
  controlledProgress: string;
  pendingCustomerAction: boolean;
  compensationFlowExists: boolean;
};

type OrderGroup = {
  orderReference: string;
  tickets: TicketSummary[];
  pendingCustomerItems: Array<{ ticketId: string; type: string; customerQuestion: string }>;
};

export function OrderTicketGroups({
  onOpenTicket,
  autoLoad = false,
}: {
  onOpenTicket: (ticketId: string) => void;
  autoLoad?: boolean;
}) {
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">(
    autoLoad ? "loading" : "idle",
  );
  const [groups, setGroups] = useState<OrderGroup[]>([]);

  function load() {
    setState("loading");
    void fetchGroups().then(
      (nextGroups) => {
        setGroups(nextGroups);
        setState("ready");
      },
      () => setState("error"),
    );
  }

  useEffect(() => {
    let active = true;
    if (autoLoad) {
      void fetchGroups().then(
        (nextGroups) => {
          if (!active) return;
          setGroups(nextGroups);
          setState("ready");
        },
        () => {
          if (active) setState("error");
        },
      );
    }
    return () => {
      active = false;
    };
  }, [autoLoad]);

  if (state === "idle") {
    return (
      <button className="order-overview-trigger" type="button" onClick={() => void load()}>
        查看订单工单总览
      </button>
    );
  }
  return (
    <section className="order-ticket-overview" aria-label="订单工单总览">
      <header>
        <div>
          <p className="eyebrow">ORDER SUPPORT MAP</p>
          <h2>订单工单总览</h2>
          <p>按订单导航；每张工单仍拥有独立对话、状态与处理责任。</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={state === "loading"}>
          刷新
        </button>
      </header>
      {state === "loading" && (
        <StatusNotice role="status" tone="busy">
          正在汇总每张独立工单…
        </StatusNotice>
      )}
      {state === "error" && (
        <StatusNotice role="alert" tone="danger">
          暂时无法读取订单工单总览；已有工单不会受影响，请稍后刷新。
        </StatusNotice>
      )}
      {state === "ready" && groups.length === 0 && (
        <p className="order-group-empty">当前还没有客服工单</p>
      )}
      {state === "ready" &&
        groups.map((group) => (
          <article className="order-ticket-group" key={group.orderReference}>
            <header>
              <div>
                <span>订单</span>
                <h3>订单 {group.orderReference}</h3>
              </div>
              <strong>{group.tickets.length} 张独立工单</strong>
            </header>
            <div className="order-ticket-grid">
              {group.tickets.map((ticket) => (
                <article aria-label={`独立工单 ${ticket.ticketId}`} key={ticket.ticketId}>
                  <div className="order-ticket-number">{shortTicketId(ticket.ticketId)}</div>
                  <h4>{issueLabel(ticket.issueKind)}</h4>
                  <dl>
                    <div>
                      <dt>状态</dt>
                      <dd>{lifecycleLabel(ticket.lifecycleState)}</dd>
                    </div>
                    <div>
                      <dt>处理</dt>
                      <dd>{ticket.handlingMode === "HUMAN" ? "人工客服" : "Agent"}</dd>
                    </div>
                    <div>
                      <dt>进度</dt>
                      <dd>{progressLabel(ticket.controlledProgress)}</dd>
                    </div>
                  </dl>
                  {ticket.compensationFlowExists && (
                    <span className="compensation-chip">补偿流程中</span>
                  )}
                  <button
                    type="button"
                    onClick={() => onOpenTicket(ticket.ticketId)}
                    aria-label={`打开工单 ${ticket.ticketId}`}
                  >
                    打开独立对话
                  </button>
                </article>
              ))}
            </div>
            {group.pendingCustomerItems.length > 0 && (
              <ol
                aria-label={`${group.orderReference} 待客户事项`}
                className="pending-customer-items"
              >
                {group.pendingCustomerItems.map((item) => (
                  <li key={`${item.ticketId}-${item.type}`}>
                    <span>{shortTicketId(item.ticketId)}</span>
                    <p>{item.customerQuestion}</p>
                    <button type="button" onClick={() => onOpenTicket(item.ticketId)}>
                      去回复
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </article>
        ))}
    </section>
  );
}

async function fetchGroups() {
  const response = await humanSessionFetch("/api/customer/v2/order-ticket-groups", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw new Error("group request failed");
  const parsed = parseResponse((await response.json()) as unknown);
  if (!parsed) throw new Error("incompatible group response");
  return parsed;
}

function parseResponse(value: unknown): OrderGroup[] | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ["view", "schema", "groups"]) ||
    value.view !== "CUSTOMER_ORDER_TICKET_GROUPS" ||
    value.schema !== SCHEMA ||
    !Array.isArray(value.groups) ||
    !value.groups.every(isOrderGroup)
  )
    return null;
  return value.groups;
}

function isOrderGroup(value: unknown): value is OrderGroup {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["orderReference", "tickets", "pendingCustomerItems"]) &&
    typeof value.orderReference === "string" &&
    Array.isArray(value.tickets) &&
    value.tickets.every(isTicketSummary) &&
    Array.isArray(value.pendingCustomerItems) &&
    value.pendingCustomerItems.every(isPendingItem)
  );
}

function isTicketSummary(value: unknown): value is TicketSummary {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "ticketId",
      "issueKind",
      "lifecycleState",
      "handlingMode",
      "controlledProgress",
      "pendingCustomerAction",
      "compensationFlowExists",
    ]) &&
    isTicketId(value.ticketId) &&
    typeof value.issueKind === "string" &&
    typeof value.lifecycleState === "string" &&
    typeof value.handlingMode === "string" &&
    typeof value.controlledProgress === "string" &&
    typeof value.pendingCustomerAction === "boolean" &&
    typeof value.compensationFlowExists === "boolean"
  );
}

function isPendingItem(value: unknown) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["ticketId", "type", "customerQuestion"]) &&
    isTicketId(value.ticketId) &&
    typeof value.type === "string" &&
    typeof value.customerQuestion === "string"
  );
}

function isTicketId(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
}

function issueLabel(issueKind: string) {
  return (
    {
      LOGISTICS_DELAY: "物流延迟",
      PACKAGE_NOT_RECEIVED: "包裹未收到",
      DUPLICATE_CHARGE: "重复扣款",
      OTHER: "其他问题",
    }[issueKind] ?? "客服问题"
  );
}

function lifecycleLabel(state: string) {
  return (
    {
      NEW: "新建",
      INVESTIGATING: "调查中",
      WAITING_FOR_CUSTOMER: "等待客户",
      WAITING_FOR_EXTERNAL: "等待外部信息",
      RESOLVED: "已解决",
      CLOSED: "已关闭",
    }[state] ?? state
  );
}

function progressLabel(progress: string) {
  return (
    {
      WAITING_FOR_CUSTOMER: "等待你的回复",
      WAITING_FOR_EXTERNAL: "等待外部信息",
      HUMAN_HANDLING: "已转人工处理",
      AGENT_PROCESSING: "Agent 独立处理中",
      RESOLVED: "已给出结论",
      CLOSED: "已关闭",
    }[progress] ?? "状态同步中"
  );
}

function shortTicketId(ticketId: string) {
  return `${ticketId.slice(0, 8)}…${ticketId.slice(-4)}`;
}
