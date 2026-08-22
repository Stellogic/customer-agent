import { Layout, Menu } from "antd";
import { Link, Outlet, useLocation } from "react-router-dom";
import { hasCapability } from "../routePolicy";
import { CurrentSessionContext } from "../session";
import { INTERNAL_WORKSPACES, ROUTES } from "../workspaceRegistry";

export default function InternalShell() {
  const session = CurrentSessionContext.use();
  const location = useLocation();
  const items = INTERNAL_WORKSPACES.filter((workspace) =>
    hasCapability(session, workspace.capability),
  ).map((workspace) => ({
    key: workspace.path,
    label: <Link to={workspace.path}>{workspace.menuLabel}</Link>,
  }));

  return (
    <Layout className="internal-shell">
      <Layout.Sider breakpoint="lg" collapsible>
        <a className="internal-shell-brand" href={ROUTES.internalHome}>
          Stellogic
        </a>
        <nav aria-label="内部工作区">
          <Menu items={items} mode="inline" selectedKeys={[location.pathname]} theme="dark" />
        </nav>
      </Layout.Sider>
      <Layout>
        <Layout.Header className="internal-shell-header">统一内部工作台</Layout.Header>
        <Layout.Content>
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
