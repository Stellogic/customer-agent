import { Link } from "react-router-dom";
import { CustomerTrustStrip, UnimplementedHelpActions } from "../components/CustomerHelpTrust";
import { ROUTES } from "../workspaceRegistry";

export default function CustomerHelpDocs() {
  return (
    <main aria-label="帮助文档" className="customer-help-docs">
      <header>
        <p className="eyebrow">帮助文档</p>
        <h1>客户帮助中心信任说明</h1>
        <p>
          这里说明当前系统边界。Agent
          建议、人工责任、补偿待审批、已批准和已执行是不同事实；本页不会扩大尚未交付的产品承诺。
        </p>
        <Link to={ROUTES.customerHome}>返回帮助中心</Link>
      </header>

      <CustomerTrustStrip />

      <section id="ai" aria-labelledby="help-docs-ai">
        <p className="eyebrow">AI</p>
        <h2 id="help-docs-ai">AI 调查只提供建议</h2>
        <p>
          在智能客服处理中，Agent 可以调查当前工单并发送公开回复。Agent
          建议只是调查过程中的说明，不是对处理时限、补偿金额或最终结果的承诺。
        </p>
        <p>
          Agent 可以形成补偿提案，但提案仍是建议。Agent
          没有审批权，也不能执行补偿。客户看到的公开回复不会把建议说成已经获批或已经到账。
        </p>
      </section>

      <section id="human" aria-labelledby="help-docs-human">
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

      <section id="compensation" aria-labelledby="help-docs-compensation">
        <p className="eyebrow">补偿</p>
        <h2 id="help-docs-compensation">待审批、已批准与已执行不是同一件事</h2>
        <p>
          待审批表示补偿提案已提交审批人，建议尚未成为执行授权。已批准表示审批人授予执行授权，仍不等于补偿已经完成。已执行才表示补偿结果已经确认。
        </p>
        <p>
          当前客户订单工单组只会在存在补偿流程时显示「补偿流程中」。这不是已获赔，也不展开内部审批证据。本页不会提供伪造的到账查询或成功结果。
        </p>
      </section>

      <UnimplementedHelpActions />
    </main>
  );
}
