import { Sources } from "@ant-design/x";
import { useState } from "react";
import "./CustomerKnowledgeSources.css";

/** 仅供展示的元数据；调用方必须先完成服务端授权与回复引用校验。不是检索 DTO。 */
export type CustomerKnowledgeSource = Readonly<{
  title: string;
  updatedAt: string;
}>;

/** 本地展示状态，不是尚未确定的 Spring API 或 SSE 协议。 */
export type CustomerKnowledgeSourcesState =
  | { status: "ready"; sources: readonly CustomerKnowledgeSource[] }
  | { status: "loading" | "empty" | "conflict" | "error" | "recovering" };

const STATUS_TEXT = {
  loading: "正在确认本次回复的知识来源。",
  empty: "本次回复没有可展示的知识来源。",
  conflict: "知识说明与当前核验事实存在冲突，请以本工单已核验的业务事实为准。",
  error: "知识来源暂时不可用，暂不展示来源。",
  recovering: "连接恢复中，正在重新确认本次回复的知识来源。",
} as const;

/** 独立组件，尚未接入客户对话。不会检索、生成答复、缓存或恢复旧来源。 */
export function CustomerKnowledgeSources({ state }: { state: CustomerKnowledgeSourcesState }) {
  const [expanded, setExpanded] = useState(true);
  const status = state.status === "ready" && state.sources.length === 0 ? "empty" : state.status;

  return (
    <section
      aria-label="知识来源"
      aria-busy={status === "loading" || status === "recovering"}
      className={`customer-knowledge-sources customer-knowledge-sources--${status}`}
    >
      {state.status === "ready" && state.sources.length > 0 ? (
        <>
          <Sources
            title={
              <button
                type="button"
                className="customer-knowledge-sources-toggle"
                aria-expanded={expanded}
              >
                本次回复的知识来源
              </button>
            }
            expanded={expanded}
            onExpand={setExpanded}
            items={state.sources.map((source, index) => ({
              key: index,
              title: (
                <>
                  <span className="customer-knowledge-source-title">{source.title}</span>
                  <span className="customer-knowledge-source-date">
                    更新时间：<time dateTime={source.updatedAt}>{source.updatedAt}</time>
                  </span>
                </>
              ),
            }))}
          />
          <p className="customer-knowledge-sources-note">
            知识来源用于说明一般规则；订单、支付和补偿结果以本工单已核验的业务事实为准。
          </p>
        </>
      ) : (
        <p role={status === "error" ? "alert" : "status"}>
          {STATUS_TEXT[state.status === "ready" ? "empty" : state.status]}
        </p>
      )}
    </section>
  );
}
