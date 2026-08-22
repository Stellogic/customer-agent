import { Layout, Menu } from "antd";
import { Link, Outlet, useLocation } from "react-router-dom";
import { hasCapability } from "../routePolicy";
import { CurrentSessionContext } from "../session";

export default function InternalShell() {
  const session = CurrentSessionContext.use();
  const location = useLocation();
  const items = [];
  if (hasCapability(session, "SUPPORT_WORKBENCH_ACCESS")) {
    items.push({ key: "/internal/support", label: <Link to="/internal/support">客服工作区</Link> });
  }
  if (hasCapability(session, "APPROVAL_WORKBENCH_ACCESS")) {
    items.push({
      key: "/internal/approvals",
      label: <Link to="/internal/approvals">审批工作区</Link>,
    });
  }

  return (
    <Layout className="internal-shell">
      <Layout.Sider breakpoint="lg" collapsible>
        <a className="internal-shell-brand" href="/internal">
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
