import { useRef, useState } from "react";
import { Layout } from "antd";
import { Link, Outlet, useLocation } from "react-router-dom";
import { Brand } from "../components/Brand";
import { hasCapability } from "../routePolicy";
import { CurrentSessionContext } from "../session";
import { INTERNAL_WORKSPACES, ROUTES, internalWorkspace } from "../workspaceRegistry";
import { SessionLogoutButton } from "../SessionLogoutButton";
import { DevelopmentNotice } from "../components/internal/DevelopmentNotice";
import "./internal-shell.css";

export default function InternalShell() {
  const session = CurrentSessionContext.use();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const workspaces = INTERNAL_WORKSPACES.filter((workspace) =>
    hasCapability(session, workspace.capability),
  );
  const supportPath = internalWorkspace("support").path;

  function closeSidebar() {
    setCollapsed(true);
    toggleRef.current?.focus();
  }

  return (
    <Layout className="internal-shell internal-shell-extras">
      <Layout.Sider
        breakpoint="lg"
        className="internal-shell-sider"
        collapsible
        collapsed={collapsed}
        collapsedWidth={0}
        onCollapse={setCollapsed}
        trigger={null}
        width={224}
      >
        <div id="internal-sidebar" className="internal-sidebar-content" hidden={collapsed}>
          <Brand
            audience="internal"
            className="internal-shell-brand"
            to={ROUTES.internalHome}
            tone="dark"
          />
          <nav aria-label="内部工作区" className="internal-primary-nav">
            {workspaces.map((workspace) => (
              <Link
                key={workspace.id}
                to={workspace.path}
                aria-current={location.pathname === workspace.path ? "page" : undefined}
              >
                <span aria-hidden="true" className="internal-menu-mark">
                  {workspace.icon}
                </span>
                {workspace.menuLabel}
              </Link>
            ))}
          </nav>
          <nav aria-label="快捷入口" className="internal-shortcut-nav">
            <p>快捷入口</p>
            {hasCapability(session, "SUPPORT_WORKBENCH_ACCESS") && (
              <>
                <Link to={supportPath} title="在客服工作区查看当前已领取工单">
                  我的工单 <small>客服工作区</small>
                </Link>
                <Link to={supportPath} title="在客服工作区查看 SLA 违约升级队列">
                  SLA 监控 <small>违约升级队列</small>
                </Link>
              </>
            )}
            {hasCapability(session, "KNOWLEDGE_READ_ACCESS") && (
              <Link to={internalWorkspace("knowledge").path}>知识库</Link>
            )}
            <DevelopmentNotice label="模板中心" />
          </nav>
          <div className="internal-sidebar-footer">
            <p>按当前职责显示工作区入口</p>
            <button type="button" onClick={closeSidebar}>
              收起侧栏
            </button>
          </div>
        </div>
      </Layout.Sider>
      <Layout className="internal-shell-body">
        <Layout.Header aria-label="内部工作台" className="internal-shell-header">
          <div>
            <Link to={ROUTES.internalHome}>
              <strong>统一内部工作台</strong>
            </Link>
            <span>当前工作人员：{session.displayName}</span>
          </div>
          <div className="shell-session">
            <button
              type="button"
              ref={toggleRef}
              aria-label={collapsed ? "展开侧栏" : "收起导航侧栏"}
              aria-expanded={!collapsed}
              aria-controls="internal-sidebar"
              onClick={() => setCollapsed(!collapsed)}
            >
              <span aria-hidden="true">☰</span>
              <span>{collapsed ? "展开侧栏" : "侧栏"}</span>
            </button>
            <a
              className="internal-resync"
              href={`${location.pathname}${location.search}`}
              title="重新加载当前页面并重新确认身份；未提交的本地输入会丢失"
            >
              重新同步
            </a>
            <DevelopmentNotice label="通知中心" />
            <SessionLogoutButton />
          </div>
        </Layout.Header>
        <Layout.Content>
          <p className="internal-resync-note">
            重新同步会重载当前页并重新确认身份，未提交的输入不会保留；同步结果以工作区反馈为准。
          </p>
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
