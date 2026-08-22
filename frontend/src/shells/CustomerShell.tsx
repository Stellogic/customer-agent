import { Layout } from "antd";
import { Outlet } from "react-router-dom";
import { SessionLogoutButton } from "../SessionLogoutButton";

export default function CustomerShell() {
  return (
    <Layout className="customer-shell">
      <Layout.Header aria-label="客户帮助中心" className="customer-shell-header">
        <a href="/help">Stellogic 帮助中心</a>
        <span>客户服务</span>
        <SessionLogoutButton />
      </Layout.Header>
      <Layout.Content>
        <Outlet />
      </Layout.Content>
    </Layout>
  );
}
