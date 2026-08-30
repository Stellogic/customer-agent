import ProCard from "@ant-design/pro-components/es/card";
import { Link } from "react-router-dom";
import { hasCapability } from "../routePolicy";
import { CurrentSessionContext } from "../session";
import { INTERNAL_WORKSPACES } from "../workspaceRegistry";

export default function InternalLanding() {
  const session = CurrentSessionContext.use();
  return (
    <main className="workspace-choice">
      <header className="workspace-choice-header">
        <p className="eyebrow">INTERNAL WORKSPACE</p>
        <h1>选择工作区</h1>
        <p>这里只展示当前身份获准进入的静态入口，不读取客服队列或审批业务数据。</p>
        <span className="workspace-current-person">当前工作人员：{session.displayName}</span>
      </header>
      <ProCard className="workspace-choice-grid" gutter={18} wrap>
        {INTERNAL_WORKSPACES.filter((workspace) =>
          hasCapability(session, workspace.capability),
        ).map((workspace) => (
          <ProCard
            className={"workspace-choice-card workspace-choice-card-" + workspace.id}
            key={workspace.id}
            colSpan={{ xs: 24, md: 12 }}
          >
            <article>
              <span aria-hidden="true" className="workspace-choice-icon">
                {workspace.icon}
              </span>
              <p className="workspace-choice-eyebrow">{workspace.eyebrow}</p>
              <h2>{workspace.cardLabel}</h2>
              <p>{workspace.description}</p>
              <Link to={workspace.path}>进入{workspace.menuLabel}</Link>
            </article>
          </ProCard>
        ))}
      </ProCard>
    </main>
  );
}
