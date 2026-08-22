import ProCard from "@ant-design/pro-components/es/card";
import { Link } from "react-router-dom";
import { hasCapability } from "../routePolicy";
import { CurrentSessionContext } from "../session";

export default function InternalLanding() {
  const session = CurrentSessionContext.use();
  return (
    <main className="workspace-choice">
      <p className="eyebrow">INTERNAL WORKSPACE</p>
      <h1>选择工作区</h1>
      <p>这里只展示页面入口，不读取客服队列或审批业务数据。</p>
      <ProCard className="workspace-choice-grid" gutter={18} wrap>
        {hasCapability(session, "SUPPORT_WORKBENCH_ACCESS") && (
          <ProCard colSpan={{ xs: 24, md: 12 }}>
            <Link to="/internal/support">客服工作区 · 调查与响应</Link>
          </ProCard>
        )}
        {hasCapability(session, "APPROVAL_WORKBENCH_ACCESS") && (
          <ProCard colSpan={{ xs: 24, md: 12 }}>
            <Link to="/internal/approvals">审批工作区 · 补偿审查</Link>
          </ProCard>
        )}
      </ProCard>
    </main>
  );
}
