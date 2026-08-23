import { FormEvent, useEffect, useState } from "react";
import type { CurrentSession } from "./authContract";
import { Brand } from "./components/Brand";
import { StatusNotice } from "./components/SystemState";
import { loadCsrfToken, type CsrfToken } from "./csrf";
import { logoutHumanSession } from "./humanSessionActions";
import { loadCurrentSession, loadOptionalCurrentSession } from "./session";
import { announceHumanSessionChange, humanSessionFetch } from "./humanSessionLifecycle";

type LoginAudience = "customer" | "internal";
const LOGIN_COPY = {
  customer: {
    eyebrow: "CUSTOMER CARE",
    storyTitle: "让每一次求助，都有清晰的下一步。",
    storyLead: "从安全登录开始，在同一个客户帮助中心查看仅属于你的服务进展。",
    regionLabel: "客户服务说明",
    points: ["只呈现客户可见的信息", "会话与身份由服务端确认", "连接变化提供清晰反馈"],
    formLead: "使用客户账号进入帮助中心。",
    securityNote: "同源 HttpOnly Session 与 CSRF 防护",
  },
  internal: {
    eyebrow: "INTERNAL OPERATIONS",
    storyTitle: "专注处理，清晰切换职责。",
    storyLead: "内部入口与客户入口保持分离；登录后仅按当前页面能力进入对应工作区。",
    regionLabel: "内部工作说明",
    points: ["客服与审批职责保持分离", "只进入当前身份允许的工作区", "工作区选择不预读业务数据"],
    formLead: "使用内部账号进入客服或补偿审批工作区。",
    securityNote: "单一当前主体 · 同源安全会话",
  },
} as const;
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
    void Promise.all([loadCsrfToken(), loadDemoAccounts(), loadOptionalCurrentSession()])
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
      const response = await humanSessionFetch("/api/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          [csrf.headerName]: csrf.token,
        },
        body: new URLSearchParams({ username, password }),
      });
      if (!response.ok) throw new Error("login rejected");
      const [nextCsrf, session] = await Promise.all([loadCsrfToken(), loadCurrentSession()]);
      setCsrf(nextCsrf);
      announceHumanSessionChange("subject-replaced");
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
      setCsrf(await logoutHumanSession());
      setCurrent(undefined);
      setUsername("");
      setPassword("");
    } catch {
      setError("退出失败，请刷新页面确认当前 Session。");
    } finally {
      setPending(false);
    }
  }

  const copy = LOGIN_COPY[audience];
  const title = audience === "customer" ? "客户登录" : "内部工作人员登录";

  return (
    <main className={"login-page login-page-" + audience}>
      <div className="login-page-frame">
        <header className="login-page-brand">
          <Brand
            audience={audience}
            to={audience === "customer" ? "/help/login" : "/internal/login"}
            tone={audience === "customer" ? "light" : "dark"}
          />
        </header>
        <div className="login-layout">
          <section aria-label={copy.regionLabel} className="login-story">
            <p className="eyebrow">{copy.eyebrow}</p>
            <h2>{copy.storyTitle}</h2>
            <p className="login-story-lead">{copy.storyLead}</p>
            <ul className="login-assurances">
              {copy.points.map((point, index) => (
                <li key={point}>
                  <span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                  {point}
                </li>
              ))}
            </ul>
          </section>
          <section aria-labelledby="login-title" className="login-card">
            {!initialized ? (
              <div className="login-restoring" role="status">
                <span aria-hidden="true" className="login-restoring-mark" />
                正在恢复当前身份…
              </div>
            ) : current ? (
              <>
                <p className="eyebrow">AUTHENTICATED SESSION</p>
                <h1 id="login-title">当前身份：{current.displayName}</h1>
                <p className="login-card-lead">服务端已恢复当前 Session。</p>
                <button disabled={!csrf || pending} onClick={() => void logout()}>
                  {pending ? "正在退出…" : "退出登录"}
                </button>
              </>
            ) : (
              <>
                <p className="eyebrow">{audience === "customer" ? "WELCOME" : "STAFF ACCESS"}</p>
                <h1 id="login-title">{title}</h1>
                <p className="login-card-lead">{copy.formLead}</p>
                <form className="login-form" onSubmit={(event) => void submit(event)}>
                  <label>
                    用户名
                    <input
                      aria-label="用户名"
                      autoComplete="username"
                      placeholder={audience === "customer" ? "请输入客户账号" : "请输入内部账号"}
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
                      placeholder="请输入密码"
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      required
                    />
                  </label>
                  <button disabled={!csrf || pending}>{pending ? "正在登录…" : "登录"}</button>
                </form>
                {demoAccounts.length > 0 && (
                  <section className="demo-accounts" aria-label="本地演示账号">
                    <h2>本地演示账号</h2>
                    <p>以下按钮只填充表单，仍需提交密码登录。</p>
                    <div className="demo-account-actions">
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
                    </div>
                  </section>
                )}
                <p className="login-security-note">
                  <span aria-hidden="true">◆</span>
                  {copy.securityNote}
                </p>
              </>
            )}
            {error && (
              <StatusNotice className="login-error" role="alert" tone="danger">
                {error}
              </StatusNotice>
            )}
          </section>
        </div>
      </div>
    </main>
  );
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
