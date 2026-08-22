export type CsrfToken = { token: string; headerName: string };

export async function loadCsrfToken(): Promise<CsrfToken> {
  const response = await fetch("/api/auth/csrf", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw new Error("csrf unavailable");
  const value = (await response.json()) as unknown;
  if (!isCsrfToken(value)) throw new Error("invalid csrf response");
  return value;
}

function isCsrfToken(value: unknown): value is CsrfToken {
  if (!isRecord(value)) return false;
  return typeof value.token === "string" && typeof value.headerName === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
