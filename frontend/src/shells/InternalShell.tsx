import { Layout, Menu } from "antd";
import { Link, Outlet, useLocation } from "react-router-dom";
import { Brand } from "../components/Brand";
import { hasCapability } from "../routePolicy";
import { CurrentSessionContext } from "../session";
import { INTERNAL_WORKSPACES, ROUTES } from "../workspaceRegistry";
import { SessionLogoutButton } from "../SessionLogoutButton";

export default function InternalShell() {
  const session = CurrentSessionContext.use();
  const location = useLocation();
  const items = INTERNAL_WORKSPACES.filter((workspace) =>
    hasCapability(session, workspace.capability),
  ).map((workspace) => ({
    key: workspace.path,
    label: (
      <Link to={workspace.path}>
        <span aria-hidden="true" className="internal-menu-mark">
          {workspace.id === "support" ? "服" : workspace.id === "approvals" ? "审" : "知"}
        </span>
        {workspace.menuLabel}
      </Link>
    ),
  }));

  return (
    <Layout className="internal-shell">
      <Layout.Sider breakpoint="lg" className="internal-shell-sider" collapsible width={232}>
        <Brand
          audience="internal"
          className="internal-shell-brand"
          to={ROUTES.internalHome}
          tone="dark"
        />
        <nav aria-label="内部工作区">
          <Menu items={items} mode="inline" selectedKeys={[location.pathname]} theme="dark" />
        </nav>
        <p className="internal-shell-boundary">按当前职责显示工作区入口</p>
      </Layout.Sider>
      <Layout>
        <Layout.Header aria-label="内部工作台" className="internal-shell-header">
          <div>
            <strong>统一内部工作台</strong>
            <span>当前工作人员：{session.displayName}</span>
          </div>
          <div className="shell-session">
            <span>安全会话</span>
            <SessionLogoutButton />
          </div>
        </Layout.Header>
        <Layout.Content>
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
