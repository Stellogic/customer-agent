import { useState } from "react";
import { Link } from "react-router-dom";
import { StatusNotice } from "./SystemState";
import { ROUTES } from "../workspaceRegistry";

const UNIMPLEMENTED_HELP_ITEMS = ["服务时间承诺", "安全保障说明全文", "补偿到账明细"] as const;

export function CustomerTrustStrip() {
  return (
    <section aria-label="信任说明" className="customer-trust-strip">
      <article>
        <strong>确认后才创建工单</strong>
        <span>先理解你的描述；未经你确认，不会创建正式客服工单。</span>
      </article>
      <article>
        <strong>信息用于处理问题</strong>
        <span>登录会话保护账号；公开沟通只展示你可以看见的内容。</span>
      </article>
      <article>
        <strong>不承诺回复时限</strong>
        <span>进展会更新到同一张工单；系统不会保证具体回复时间。</span>
      </article>
    </section>
  );
}

export function CustomerCapabilityGuide() {
  return (
    <section aria-labelledby="customer-capability-title" className="customer-capability-guide">
      <div>
        <p className="eyebrow">能力边界</p>
        <h2 id="customer-capability-title">AI、人工与补偿如何分工</h2>
        <p>这三块说明当前产品边界，不会把建议说成决定，也不会把待审批说成已获赔。</p>
      </div>
      <div className="customer-capability-cards">
        <article aria-labelledby="customer-capability-ai">
          <p className="eyebrow">AI</p>
          <h3 id="customer-capability-ai">AI 调查</h3>
          <p className="customer-capability-badge">建议，不是决定</p>
          <p>
            Agent
            可以在智能客服处理中调查并公开回复。它提出的理解、建议或补偿方案都只是建议，不能自行批准或执行补偿，也不构成对结果或时限的承诺。
          </p>
          <Link to={`${ROUTES.customerDocs}#ai`}>阅读 AI 说明</Link>
        </article>
        <article aria-labelledby="customer-capability-human">
          <p className="eyebrow">人工</p>
          <h3 id="customer-capability-human">人工客服</h3>
          <p className="customer-capability-badge">人工承担责任</p>
          <p>
            转为人工客服处理后，由负责客服承担公开回复责任。此时 Agent
            只能提供内部辅助，不能越过人工责任发送消息或决定补偿。
          </p>
          <Link to={`${ROUTES.customerDocs}#human`}>阅读人工说明</Link>
        </article>
        <article aria-labelledby="customer-capability-compensation">
          <p className="eyebrow">补偿</p>
          <h3 id="customer-capability-compensation">补偿审批</h3>
          <p className="customer-capability-badge">待审批不是已获赔</p>
          <p>
            补偿提案处于待审批时，只说明建议已提交审批人。已批准表示获得执行授权，仍不等于已经执行；已执行才是确认结果。当前订单工单组只会提示「补偿流程中」，不会把待审批说成已获赔。
          </p>
          <Link to={`${ROUTES.customerDocs}#compensation`}>阅读补偿说明</Link>
        </article>
      </div>
      <UnimplementedHelpActions />
    </section>
  );
}

export function UnimplementedHelpActions() {
  const [notice, setNotice] = useState("");

  return (
    <div className="customer-help-unimplemented" aria-label="尚未提供的帮助条目">
      <p>尚未写成独立页面的帮助条目会明确显示开发中，点击不会发送写请求。</p>
      <div className="customer-help-unimplemented-actions">
        {UNIMPLEMENTED_HELP_ITEMS.map((label) => (
          <button
            key={label}
            type="button"
            onClick={() =>
              setNotice(
                `${label}入口正在开发中；本次点击不会发送写请求，也不会改变工单或补偿状态。`,
              )
            }
          >
            {label}（开发中）
          </button>
        ))}
      </div>
      {notice && <StatusNotice role="status">{notice}</StatusNotice>}
    </div>
  );
}
