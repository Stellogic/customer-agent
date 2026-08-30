import { useId, useState } from "react";
import "./support-assistance.css";

const assistanceLabels = {
  summary: "工单总结",
  knowledge: "知识检索",
  policy: "政策查询",
  draft: "回复草稿",
} as const;

// 仅为本组件的展示模型，不是 #169 的共享 Agent 或 HTTP 契约。
export type AssistanceKind = keyof typeof assistanceLabels;
export type AssistanceView =
  | { status: "idle" }
  | { status: "loading"; kind: AssistanceKind }
  | { status: "empty"; kind: AssistanceKind }
  | { status: "error"; reason: "conflict" | "index" | "model" }
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
        snippet: string;
        applicability: string[];
      }>;
    };

export type SupportAssistancePanelProps = {
  // 宿主只在当前负责客服 + HUMAN + 权威投影有效时提供非空键。
  // 键必须区分会话身份、工单和责任代次；撤权/断线重同步时立即传 null。
  projectionKey: string | null;
  view: { projectionKey: string; content: AssistanceView } | null;
  // 只将已审阅的文本填入现有人工 composer；不得在此回调直接发送。
  // null 表示尚未接线或既有人工发送正在处理中/结果未确认。
  onReviewDraft: ((text: string) => void) | null;
};

export function SupportAssistancePanel(props: SupportAssistancePanelProps) {
  if (props.projectionKey === null) {
    return <p role="status">当前无有效人工处理权限，辅助内容与草稿已清除。</p>;
  }
  return (
    <AuthorizedAssistance
      key={props.projectionKey}
      view={props.view?.projectionKey === props.projectionKey ? props.view.content : { status: "idle" }}
      onReviewDraft={props.onReviewDraft}
    />
  );
}

function AuthorizedAssistance({
  view,
  onReviewDraft,
}: {
  view: AssistanceView;
  onReviewDraft: SupportAssistancePanelProps["onReviewDraft"];
}) {
  const titleId = useId();
  const [draft, setDraft] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [notice, setNotice] = useState("");
  const [replaceRequestId, setReplaceRequestId] = useState<string | null>(null);
  const candidate = view.status === "ready" && view.kind === "draft" ? view.text : null;

  function editDraft(text: string) {
    setDraft(text);
    setReviewed(false);
    setNotice("");
    setReplaceRequestId(null);
  }

  function insertDraft() {
    if (candidate === null || candidate.length > 2000) return;
    editDraft(candidate);
    setNotice("已填入内部草稿，请编辑并人工审阅；尚未发送。");
  }

  return (
    <section className="support-assistance" aria-labelledby={titleId}>
      <header className="support-assistance__heading">
        <span className="support-assistance__mark" aria-hidden="true">✧</span>
        <div>
          <h3 id={titleId}>AI 智能辅助</h3>
          <p>当前工单 · 仅内部可见 · 由客服审阅</p>
        </div>
      </header>
      <nav className="support-assistance__actions" aria-label="辅助类型">
        {Object.entries(assistanceLabels).map(([kind, label]) => (
          <button
            key={kind}
            type="button"
            onClick={() => setNotice(`${label}接入开发中，未发起 Agent 请求。`)}
          >
            {label}
          </button>
        ))}
      </nav>
      <p className="support-assistance__hint">辅助接入开发中；不会执行建议、修改工单或提交补偿。</p>

      <div className="support-assistance__result" aria-busy={view.status === "loading"}>
        {view.status === "idle" && <p>暂无辅助结果，可继续人工编辑回复。</p>}
        {view.status === "loading" && <p role="status">正在准备{assistanceLabels[view.kind]}…</p>}
        {view.status === "empty" && <p role="status">{assistanceLabels[view.kind]}暂无可用答案，请人工核实。</p>}
        {view.status === "error" && (
          <p role="alert">
            {{ conflict: "知识存在冲突，请人工核实适用政策。", index: "知识索引暂不可用。", model: "模型辅助暂不可用。" }[view.reason]}
            人工处理不受影响。
          </p>
        )}
        {view.status === "ready" && (
          <>
            <h4>{assistanceLabels[view.kind]}</h4>
            <small>请求标识：{view.requestId}</small>
            <p className="support-assistance__text">{view.text}</p>
            {view.suggestions.length > 0 && (
              <>
                <h4>AI 建议操作</h4>
                <p className="support-assistance__hint">仅供人工判断，不会自动执行。</p>
                <ul>{view.suggestions.map((text, index) => <li key={index}>{text}</li>)}</ul>
              </>
            )}
            <h4>知识引用</h4>
            {view.citations.length === 0 ? <p>没有可展示的知识引用。</p> : (
              <ul className="support-assistance__citations">
                {view.citations.map((citation) => (
                  <li key={`${citation.articleId}:${citation.version}:${citation.chunkId}`}>
                    <strong>{citation.title}</strong>
                    <dl>
                      <div><dt>版本</dt><dd>{citation.version}</dd></div>
                      <div><dt>内部标识</dt><dd>{citation.articleId} / {citation.chunkId}</dd></div>
                      <div><dt>适用范围</dt><dd>{citation.applicability.join("、")}</dd></div>
                    </dl>
                    <blockquote>{citation.snippet}</blockquote>
                  </li>
                ))}
              </ul>
            )}
            {candidate !== null && (
              <div className="support-assistance__insert" key={view.requestId}>
                <button
                  type="button"
                  disabled={!candidate.trim() || candidate.length > 2000}
                  onClick={() => draft.trim() ? setReplaceRequestId(view.requestId) : insertDraft()}
                >插入回复草稿</button>
                {candidate.length > 2000 && <p role="alert">辅助草稿超过 2000 字，请人工编写；不会截断后发送。</p>}
                {replaceRequestId === view.requestId && (
                  <div role="group" aria-label="确认替换草稿">
                    <p>编辑区已有内容，是否用当前辅助草稿替换？</p>
                    <button type="button" onClick={insertDraft}>确认替换</button>
                    <button type="button" onClick={() => setReplaceRequestId(null)}>保留当前编辑</button>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <section className="support-assistance__composer" aria-label="辅助草稿编辑">
        <h4>回复草稿</h4>
        <label>
          内部编辑区（尚未发送）
          <textarea rows={5} maxLength={2000} value={draft} onChange={(event) => editDraft(event.target.value)} />
        </label>
        <small>{draft.length}/2000</small>
        <label className="support-assistance__review">
          <input type="checkbox" checked={reviewed} disabled={!draft.trim()} onChange={(event) => setReviewed(event.target.checked)} />
          我已核实事实、政策与客户可见措辞
        </label>
        <button
          type="button"
          disabled={!draft.trim() || !reviewed || onReviewDraft === null}
          onClick={() => {
            if (!reviewed || !draft.trim() || onReviewDraft === null) return;
            onReviewDraft(draft.trim());
            setReviewed(false);
            setNotice("已交给人工发送区；仍需在那里显式发送，尚未发送给客户。");
          }}
        >交给人工发送区</button>
        {onReviewDraft === null && <p className="support-assistance__hint">人工发送衔接当前不可用；可继续编辑，不会发送。</p>}
        <p className="support-assistance__hint">最终发送仍由 Spring 校验当前责任、HUMAN 模式与请求幂等。</p>
      </section>
      {notice && <p className="support-assistance__notice" role="status">{notice}</p>}
    </section>
  );
}
