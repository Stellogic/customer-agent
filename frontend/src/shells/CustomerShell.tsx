import { Layout } from "antd";
import { NavLink, Outlet } from "react-router-dom";
import { Brand } from "../components/Brand";
import { SessionLogoutButton } from "../SessionLogoutButton";
import { CurrentSessionContext } from "../session";
import { ROUTES } from "../workspaceRegistry";

export default function CustomerShell() {
  const session = CurrentSessionContext.use();
  return (
    <Layout className="customer-shell">
      <Layout.Header aria-label="客户帮助中心" className="customer-shell-header">
        <Brand audience="customer" to={ROUTES.customerHome} />
        <nav aria-label="客户导航" className="customer-shell-nav">
          <NavLink end to={ROUTES.customerHome}>
            帮助中心
          </NavLink>
          <NavLink to={ROUTES.customerDocs}>帮助文档</NavLink>
        </nav>
        <div className="shell-session">
          <span>当前客户：{session.displayName}</span>
          <SessionLogoutButton />
        </div>
      </Layout.Header>
      <Layout.Content>
        <Outlet />
      </Layout.Content>
    </Layout>
  );
}
