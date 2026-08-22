import { FormEvent, useEffect, useState } from "react";
import type { CurrentSession } from "./routePolicy";
import { loadCurrentSession, loadOptionalCurrentSession } from "./session";

type LoginAudience = "customer" | "internal";
type CsrfToken = { token: string; headerName: string };
type DemoAccount = {
  username: string;
  displayName: string;
  subjectType: "CUSTOMER" | "INTERNAL";
  password: string;
};
export function LoginPage({
  audience,
  onAuthenticated,
}: {
  audience: LoginAudience;
  onAuthenticated?: (session: CurrentSession) => void;
}) {
  const [csrf, setCsrf] = useState<CsrfToken>();
  const [demoAccounts, setDemoAccounts] = useState<DemoAccount[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [current, setCurrent] = useState<CurrentSession>();
  const [initialized, setInitialized] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void Promise.all([loadCsrf(), loadDemoAccounts(), loadOptionalCurrentSession()])
      .then(([nextCsrf, accounts, restoredSession]) => {
        if (!active) return;
        setCsrf(nextCsrf);
        if (restoredSession && onAuthenticated) onAuthenticated(restoredSession);
        else setCurrent(restoredSession);
        setDemoAccounts(
          accounts.filter((account) =>
            audience === "customer"
              ? account.subjectType === "CUSTOMER"
              : account.subjectType === "INTERNAL",
          ),
        );
        setInitialized(true);
      })
      .catch(() => {
        if (active) {
          setError("无法初始化安全登录，请刷新后重试。");
          setInitialized(true);
        }
      });
    return () => {
      active = false;
    };
  }, [audience, onAuthenticated]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!csrf || pending) return;
    setPending(true);
    setError("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          [csrf.headerName]: csrf.token,
        },
        body: new URLSearchParams({ username, password }),
      });
      if (!response.ok) throw new Error("login rejected");
      const [nextCsrf, session] = await Promise.all([loadCsrf(), loadCurrentSession()]);
      setCsrf(nextCsrf);
      if (onAuthenticated) onAuthenticated(session);
      else setCurrent(session);
      setPassword("");
    } catch {
      setError("用户名或密码错误，请重新输入。");
    } finally {
      setPending(false);
    }
  }

  async function logout() {
    if (!csrf || pending) return;
    setPending(true);
    setError("");
    try {
      const response = await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { [csrf.headerName]: csrf.token },
      });
      if (!response.ok) throw new Error("logout rejected");
      setCsrf(await loadCsrf());
      setCurrent(undefined);
      setUsername("");
      setPassword("");
    } catch {
      setError("退出失败，请刷新页面确认当前 Session。");
    } finally {
      setPending(false);
    }
  }

  const title = audience === "customer" ? "客户登录" : "内部工作人员登录";
  if (!initialized) {
    return (
      <main className="login-page">
        <p role="status">正在恢复当前身份…</p>
      </main>
    );
  }
  if (current) {
    return (
      <main className="login-page">
        <p className="eyebrow">AUTHENTICATED SESSION</p>
        <h1>当前身份：{current.displayName}</h1>
        <p>Session 已由服务端恢复。后续工作区路由将在独立票据中接入。</p>
        <button disabled={!csrf || pending} onClick={() => void logout()}>
          {pending ? "正在退出…" : "退出登录"}
        </button>
        {error && <p role="alert">{error}</p>}
      </main>
    );
  }

  return (
    <main className="login-page">
      <p className="eyebrow">SECURE SESSION</p>
      <h1>{title}</h1>
      <p>使用真实密码校验建立同源 HttpOnly Session。</p>
      <form className="login-form" onSubmit={(event) => void submit(event)}>
        <label>
          用户名
          <input
            aria-label="用户名"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label>
          密码
          <input
            aria-label="密码"
            autoComplete="current-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        <button disabled={!csrf || pending}>{pending ? "正在登录…" : "登录"}</button>
      </form>
      {error && <p role="alert">{error}</p>}
      {demoAccounts.length > 0 && (
        <section className="demo-accounts" aria-label="本地演示账号">
          <h2>本地演示账号</h2>
          <p>以下按钮只填充表单，仍需提交密码登录。</p>
          {demoAccounts.map((account) => (
            <button
              key={account.username}
              type="button"
              onClick={() => {
                setUsername(account.username);
                setPassword(account.password);
              }}
            >
              使用{account.displayName}填充
            </button>
          ))}
        </section>
      )}
    </main>
  );
}

async function loadCsrf(): Promise<CsrfToken> {
  const response = await fetch("/api/auth/csrf", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw new Error("csrf unavailable");
  const value = (await response.json()) as unknown;
  if (!isCsrfToken(value)) throw new Error("invalid csrf response");
  return value;
}

async function loadDemoAccounts(): Promise<DemoAccount[]> {
  const response = await fetch("/api/auth/demo-accounts", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) return [];
  const value = (await response.json()) as unknown;
  if (!Array.isArray(value)) return [];
  return value.filter(isDemoAccount);
}

function isCsrfToken(value: unknown): value is CsrfToken {
  if (!isRecord(value)) return false;
  return typeof value.token === "string" && typeof value.headerName === "string";
}

function isDemoAccount(value: unknown): value is DemoAccount {
  if (!isRecord(value)) return false;
  return (
    typeof value.username === "string" &&
    typeof value.displayName === "string" &&
    (value.subjectType === "CUSTOMER" || value.subjectType === "INTERNAL") &&
    typeof value.password === "string"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
