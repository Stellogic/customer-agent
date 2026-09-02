import { DevelopmentNotice } from "./DevelopmentNotice";
import "./context-entries.css";

// available 只接收宿主对当前授权投影的查看/定位操作，不承载业务写入。
// 集成方必须明确区分尚无能力和当前无权访问，不能用默认占位覆盖既有能力。
export type ContextEntry =
  | { kind: "available"; onOpen: () => void; description?: string }
  | { kind: "developing" }
  | { kind: "unavailable"; reason: string };

type Entry = { label: string; action: ContextEntry };

function EntryList({ entries }: { entries: Entry[] }) {
  return (
    <ul className="context-entry-list">
      {entries.map(({ label, action }) => (
        <li key={label}>
          {action.kind === "available" ? (
            <>
              <button type="button" onClick={action.onOpen}>
                {label}
              </button>
              {action.description && <small>{action.description}</small>}
            </>
          ) : action.kind === "developing" ? (
            <DevelopmentNotice label={label} />
          ) : (
            <>
              <button type="button" disabled>
                {label}
              </button>
              <small>{action.reason}</small>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

export type SupportContextEntriesProps = {
  // 由当前负责客服投影的宿主提供身份/责任/版本键；撤权或同步时传 null。
  projectionKey: string | null;
  entries: {
    transfer: ContextEntry;
    more: ContextEntry;
    order: ContextEntry;
    logistics: ContextEntry;
    contact: ContextEntry;
    similarCases: ContextEntry;
    suggestedActions: ContextEntry;
  };
};

export function SupportContextEntries({ projectionKey, entries }: SupportContextEntriesProps) {
  if (projectionKey === null) {
    return <p role="status">当前没有可用的客服授权详情，相关入口已移除。</p>;
  }
  return (
    <section className="context-entries" aria-label="客服详情入口" key={projectionKey}>
      <header>
        <p>当前负责客服</p>
        <h3>工单相关入口</h3>
      </header>
      <EntryList
        entries={[
          { label: "转派", action: entries.transfer },
          { label: "更多操作", action: entries.more },
          { label: "查看订单", action: entries.order },
          { label: "查看物流", action: entries.logistics },
          { label: "联系客户", action: entries.contact },
          { label: "相似案例", action: entries.similarCases },
          { label: "建议动作", action: entries.suggestedActions },
        ]}
      />
    </section>
  );
}

export type ApprovalContextEntriesProps = {
  // 由当前有效审批租约的宿主提供投影版本键，不读取客服详情或其他工单。
  projectionKey: string | null;
  entries: {
    policy: ContextEntry;
    proposalLog: ContextEntry;
    logistics: ContextEntry;
    eligibility: ContextEntry;
  };
};

export function ApprovalContextEntries({ projectionKey, entries }: ApprovalContextEntriesProps) {
  if (projectionKey === null) {
    return <p role="status">当前没有可用的审批授权详情，相关入口已移除。</p>;
  }
  return (
    <section className="context-entries" aria-label="审批详情入口" key={projectionKey}>
      <header>
        <p>当前审批视图</p>
        <h3>审批参考入口</h3>
      </header>
      <EntryList
        entries={[
          { label: "政策详情", action: entries.policy },
          { label: "提案日志", action: entries.proposalLog },
          { label: "物流轨迹", action: entries.logistics },
          { label: "资格检查明细", action: entries.eligibility },
          {
            label: "完整对话",
            action: {
              kind: "unavailable",
              reason: "当前审批视图不授予完整客户对话访问权，请依据已授权的审批证据处理。",
            },
          },
        ]}
      />
    </section>
  );
}

export function ApprovalQueueEntries() {
  return (
    <nav className="context-entries" aria-label="审批队列辅助入口">
      <EntryList
        entries={[
          { label: "更多筛选", action: { kind: "developing" } },
          { label: "导出", action: { kind: "developing" } },
        ]}
      />
    </nav>
  );
}
