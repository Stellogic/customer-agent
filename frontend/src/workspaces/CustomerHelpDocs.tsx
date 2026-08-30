import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { CustomerTrustStrip, UnimplementedHelpActions } from "../components/CustomerHelpTrust";
import { ROUTES } from "../workspaceRegistry";

export default function CustomerHelpDocs() {
  const { hash } = useLocation();

  useEffect(() => {
    if (hash) {
      document.getElementById(hash.slice(1))?.focus();
    }
  }, [hash]);

  return (
    <main aria-label="帮助文档" className="customer-help-docs">
      <header>
        <p className="eyebrow">帮助文档</p>
        <h1>客户帮助中心信任说明</h1>
        <p>
          这里说明当前系统边界。Agent
          建议、人工责任和补偿待审批是不同事实。已批准和已执行是内部后续事实，客户帮助中心不会把它们显示为已经获得补偿。
        </p>
        <Link to={ROUTES.customerHome}>返回帮助中心</Link>
      </header>

      <CustomerTrustStrip />

      <section id="ai" aria-labelledby="help-docs-ai" tabIndex={-1}>
        <p className="eyebrow">AI</p>
        <h2 id="help-docs-ai">AI 调查只提供建议</h2>
        <p>
          在智能客服处理中，Agent 可以调查当前工单并发送公开回复。Agent
          建议只是调查过程中的说明，不是对处理时限、补偿金额或最终结果的承诺。
        </p>
        <p>
          Agent 可以形成补偿提案，但提案仍是建议。Agent
          没有审批权，也不能执行补偿。客户看到的公开回复不会把建议说成已经获批。
        </p>
      </section>

      <section id="human" aria-labelledby="help-docs-human" tabIndex={-1}>
        <p className="eyebrow">人工</p>
        <h2 id="help-docs-human">人工客服承担公开回复责任</h2>
        <p>
          当工单转为人工客服处理，公开回复责任属于负责客服。你仍可在同一张工单中继续沟通；系统不会因此自动批准补偿。
        </p>
        <p>
          此时 Agent
          只能提供内部辅助。辅助结果必须由负责客服审阅后才能发送，不能越过人工责任直接回复客户或决定补偿。
        </p>
      </section>

      <section id="compensation" aria-labelledby="help-docs-compensation" tabIndex={-1}>
        <p className="eyebrow">补偿</p>
        <h2 id="help-docs-compensation">待审批还不是已经获得补偿</h2>
        <p>
          待审批只表示补偿提案已提交审批人，建议尚未成为决定。已批准是内部执行授权，已执行才是内部确认结果；这两项都不会在客户帮助中心显示为已经获得补偿。Agent
          建议的金额或方式也不构成最终补偿。
        </p>
        <p>
          当前客户订单工单组只会在存在补偿流程时显示「补偿流程中」。这不是已获补偿，也不展开内部审批证据。本页不会提供到账查询或伪造成功结果。
        </p>
      </section>

      <UnimplementedHelpActions />
    </main>
  );
}
