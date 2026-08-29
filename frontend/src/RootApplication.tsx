import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { ConfigProvider } from "antd";
import {
  BrowserRouter,
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { LoginPage } from "./LoginPage";
import { SystemState } from "./components/SystemState";
import {
  defaultPathFor,
  hasCapability,
  loginPathFor,
  safeReturnTo,
  type CurrentSession,
  type HumanCapability,
} from "./routePolicy";
import { CurrentSessionContext, loadOptionalCurrentSession } from "./session";
import { observeHumanSession, subscribeToHumanSessionInvalidation } from "./humanSessionLifecycle";
import { INTERNAL_WORKSPACES, LEGACY_ROUTE_REDIRECTS, ROUTES } from "./workspaceRegistry";

const CustomerShell = lazy(() => import("./shells/CustomerShell"));
const InternalShell = lazy(() => import("./shells/InternalShell"));
const CustomerWorkspace = lazy(() => import("./workspaces/CustomerWorkspace"));
const InternalLanding = lazy(() => import("./workspaces/InternalLanding"));
const SupportWorkspace = lazy(() => import("./workspaces/SupportWorkspace"));
const ApprovalWorkspace = lazy(() => import("./workspaces/ApprovalWorkspace"));
const KnowledgeWorkspace = lazy(() => import("./workspaces/KnowledgeWorkspace"));
const INTERNAL_WORKSPACE_COMPONENTS = {
  support: SupportWorkspace,
  approvals: ApprovalWorkspace,
  knowledge: KnowledgeWorkspace,
} as const;

export function RootApplication() {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: "#0b382b",
          colorInfo: "#3977c6",
          colorSuccess: "#2a8a5b",
          colorWarning: "#d87920",
          colorError: "#d34f4b",
          colorText: "#14231e",
          colorBgContainer: "#fffefa",
          borderRadius: 10,
          fontFamily: 'Aptos, "Microsoft YaHei UI", "PingFang SC", sans-serif',
        },
      }}
    >
      <BrowserRouter>
        <Suspense fallback={<RouteLoading />}>
          <Routes>
            <Route path={ROUTES.customerLogin} element={<LoginRoute audience="customer" />} />
            <Route path={ROUTES.internalLogin} element={<LoginRoute audience="internal" />} />
            {LEGACY_ROUTE_REDIRECTS.map((route) => (
              <Route key={route.path} path={route.path} element={<LegacyRoute to={route.to} />} />
            ))}
            <Route element={<SessionGate />}>
              <Route index element={<DefaultLanding />} />
              <Route
                path={ROUTES.customerHome}
                element={
                  <CustomerBoundary>
                    <CapabilityBoundary capability="CUSTOMER_HELP_ACCESS">
                      <CustomerShell />
                    </CapabilityBoundary>
                  </CustomerBoundary>
                }
              >
                <Route index element={<CustomerWorkspace />} />
              </Route>
              <Route
                path={ROUTES.internalHome}
                element={
                  <InternalBoundary>
                    <InternalShell />
                  </InternalBoundary>
                }
              >
                <Route index element={<InternalLanding />} />
                {INTERNAL_WORKSPACES.map((workspace) => {
                  const Workspace = INTERNAL_WORKSPACE_COMPONENTS[workspace.id];
                  return (
                    <Route
                      key={workspace.id}
                      path={workspace.id}
                      element={
                        <CapabilityBoundary capability={workspace.capability}>
                          <Workspace />
                        </CapabilityBoundary>
                      }
                    />
                  );
                })}
              </Route>
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ConfigProvider>
  );
}

function SessionGate() {
  const location = useLocation();
  const [state, setState] = useState<
    | { status: "loading" }
    | {
        status: "authenticated";
        session: NonNullable<Awaited<ReturnType<typeof loadOptionalCurrentSession>>>;
      }
    | { status: "anonymous" }
    | { status: "error" }
  >({ status: "loading" });

  useEffect(() => {
    let active = true;
    let invalidated = false;
    const unsubscribe = subscribeToHumanSessionInvalidation(() => {
      invalidated = true;
      observeHumanSession(undefined);
      if (active) setState({ status: "anonymous" });
    });
    void loadOptionalCurrentSession()
      .then((session) => {
        if (!active || invalidated) return;
        observeHumanSession(session);
        setState(session ? { status: "authenticated", session } : { status: "anonymous" });
      })
      .catch(() => {
        if (active) setState({ status: "error" });
      });
    return () => {
      active = false;
      observeHumanSession(undefined);
      unsubscribe();
    };
  }, []);

  if (state.status === "loading") return <RouteLoading />;
  if (state.status === "error") return <RouteError />;
  if (state.status === "anonymous") {
    const returnTo = safeReturnTo(`${location.pathname}${location.search}`);
    const target = loginPathFor(location.pathname);
    const search = returnTo ? `?returnTo=${encodeURIComponent(returnTo)}` : "";
    return <Navigate replace to={`${target}${search}`} />;
  }
  return (
    <CurrentSessionContext.Provider value={state.session}>
      <Outlet />
    </CurrentSessionContext.Provider>
  );
}

function LoginRoute({ audience }: { audience: "customer" | "internal" }) {
  const location = useLocation();
  const navigate = useNavigate();
  const requestedReturnTo = safeReturnTo(new URLSearchParams(location.search).get("returnTo"));
  const handleAuthenticated = useCallback(
    (session: CurrentSession) =>
      navigate(requestedReturnTo ?? defaultPathFor(session), { replace: true }),
    [navigate, requestedReturnTo],
  );
  return <LoginPage audience={audience} onAuthenticated={handleAuthenticated} />;
}

function LegacyRoute({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate replace to={`${to}${location.search}`} />;
}

function DefaultLanding() {
  const session = CurrentSessionContext.use();
  return <Navigate replace to={defaultPathFor(session)} />;
}

function CapabilityBoundary({
  capability,
  children,
}: {
  capability: HumanCapability;
  children: ReactNode;
}) {
  const session = CurrentSessionContext.use();
  return hasCapability(session, capability) ? children : <Forbidden />;
}

function InternalBoundary({ children }: { children: ReactNode }) {
  const session = CurrentSessionContext.use();
  return session.subjectType === "INTERNAL" ? children : <Forbidden />;
}

function CustomerBoundary({ children }: { children: ReactNode }) {
  const session = CurrentSessionContext.use();
  return session.subjectType === "CUSTOMER" ? children : <Forbidden />;
}

function RouteLoading() {
  return (
    <SystemState
      announcement="status"
      announcementLabel="正在确认当前身份"
      busy
      description="正在安全地恢复你的工作区…"
      eyebrow="SECURE SESSION"
      title="正在确认当前身份"
      variant="loading"
    />
  );
}

function RouteError() {
  const location = useLocation();
  return (
    <SystemState
      actions={
        <a className="route-state-action" href={`${location.pathname}${location.search}`}>
          重新加载当前页面
        </a>
      }
      announcement="alert"
      description="当前身份暂时无法确认。请重新加载页面后再试。"
      eyebrow="CONNECTION CHECK"
      title="暂时无法进入工作区"
      variant="error"
    />
  );
}

function Forbidden() {
  const session = CurrentSessionContext.use();
  return (
    <SystemState
      actions={
        <Link className="route-state-action" to={defaultPathFor(session)}>
          返回可访问工作区
        </Link>
      }
      code="403"
      description="这里没有加载任何受保护内容。你可以返回当前身份可访问的工作区继续操作。"
      eyebrow="ACCESS BOUNDARY"
      title="当前身份无权访问此页面"
      variant="forbidden"
    />
  );
}

function NotFound() {
  return (
    <SystemState
      actions={
        <>
          <Link className="route-state-action" to={ROUTES.customerLogin}>
            前往客户登录
          </Link>
          <Link
            className="route-state-action route-state-action-secondary"
            to={ROUTES.internalLogin}
          >
            前往内部登录
          </Link>
        </>
      }
      code="404"
      description="请检查地址，或从安全登录入口重新开始。"
      eyebrow="WAYFINDING"
      title="没有找到这个页面"
      variant="not-found"
    />
  );
}
