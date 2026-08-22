import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { LoginPage } from "./LoginPage";
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
const INTERNAL_WORKSPACE_COMPONENTS = {
  support: SupportWorkspace,
  approvals: ApprovalWorkspace,
} as const;

export function RootApplication() {
  return (
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
    <main className="route-state">
      <p role="status">正在加载工作区…</p>
    </main>
  );
}

function RouteError() {
  return (
    <main className="route-state">
      <h1>无法恢复当前身份</h1>
      <p role="alert">请刷新页面后重试。</p>
    </main>
  );
}

function Forbidden() {
  return (
    <main className="route-state">
      <p className="eyebrow">ACCESS BOUNDARY</p>
      <h1>403</h1>
      <p>当前身份没有进入此页面的 capability。</p>
    </main>
  );
}

function NotFound() {
  return (
    <main className="route-state">
      <h1>404</h1>
      <p>该地址不属于已知静态路由。</p>
    </main>
  );
}
