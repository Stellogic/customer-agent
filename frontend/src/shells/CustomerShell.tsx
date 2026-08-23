import { Layout } from "antd";
import { Link, Outlet } from "react-router-dom";
import { Brand } from "../components/Brand";
import { SessionLogoutButton } from "../SessionLogoutButton";
import { CurrentSessionContext } from "../session";

export default function CustomerShell() {
  const session = CurrentSessionContext.use();
  return (
    <Layout className="customer-shell">
      <Layout.Header aria-label="客户帮助中心" className="customer-shell-header">
        <Brand audience="customer" to="/help" />
        <nav aria-label="客户导航" className="customer-shell-nav">
          <Link aria-current="page" to="/help">
            帮助中心
          </Link>
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
