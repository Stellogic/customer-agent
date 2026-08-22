import type { CurrentSession } from "./authContract";
import type { CsrfToken } from "./csrf";

export function createCookieBrowserFetch(nativeFetch: typeof fetch, baseUrl: string): typeof fetch {
  let cookie = "";
  return async (input, init) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const headers = new Headers(init?.headers);
    if (cookie) headers.set("Cookie", cookie);
    const response = await nativeFetch(new URL(path, baseUrl), { ...init, headers });
    const setCookies =
      (response.headers as Headers & { getSetCookie?: () => string[] }).getSetCookie?.() ??
      [response.headers.get("set-cookie")].filter((value): value is string => value !== null);
    const sessionCookie = setCookies.find((value) => value.startsWith("JSESSIONID="));
    if (sessionCookie) cookie = sessionCookie.split(";", 1)[0];
    return response;
  };
}

export async function loginCustomer(browserFetch: typeof fetch): Promise<CurrentSession> {
  const csrfResponse = await browserFetch("/api/auth/csrf");
  if (!csrfResponse.ok) throw new Error("customer csrf unavailable");
  const csrf = (await csrfResponse.json()) as CsrfToken;
  const login = await browserFetch("/api/auth/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      [csrf.headerName]: csrf.token,
    },
    body: new URLSearchParams({
      username: "customer-demo",
      password: "local-demo-password",
    }),
  });
  if (login.status !== 204) throw new Error("customer login failed");
  const session = await browserFetch("/api/auth/session");
  if (!session.ok) throw new Error("customer session unavailable");
  return (await session.json()) as CurrentSession;
}
