import { loadCsrfToken } from "./csrf";
import { announceHumanSessionChange, humanSessionFetch } from "./humanSessionLifecycle";

export async function logoutHumanSession() {
  const csrf = await loadCsrfToken();
  const response = await humanSessionFetch("/api/auth/logout", {
    method: "POST",
    credentials: "same-origin",
    headers: { [csrf.headerName]: csrf.token },
  });
  if (!response.ok) throw new Error("logout rejected");
  announceHumanSessionChange("logged-out");
  return loadCsrfToken();
}
