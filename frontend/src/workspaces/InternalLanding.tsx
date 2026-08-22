import ProCard from "@ant-design/pro-components/es/card";
import { Link } from "react-router-dom";
import { hasCapability } from "../routePolicy";
import { CurrentSessionContext } from "../session";
import { INTERNAL_WORKSPACES } from "../workspaceRegistry";

export default function InternalLanding() {
  const session = CurrentSessionContext.use();
  return (
    <main className="workspace-choice">
      <p className="eyebrow">INTERNAL WORKSPACE</p>
      <h1>选择工作区</h1>
      <p>这里只展示页面入口，不读取客服队列或审批业务数据。</p>
      <ProCard className="workspace-choice-grid" gutter={18} wrap>
        {INTERNAL_WORKSPACES.filter((workspace) =>
          hasCapability(session, workspace.capability),
        ).map((workspace) => (
          <ProCard key={workspace.id} colSpan={{ xs: 24, md: 12 }}>
            <Link to={workspace.path}>{workspace.cardLabel}</Link>
          </ProCard>
        ))}
      </ProCard>
    </main>
  );
}
