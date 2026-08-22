import { useState } from "react";
import { logoutHumanSession } from "./humanSessionActions";

export function SessionLogoutButton() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function logout() {
    if (pending) return;
    setPending(true);
    setError("");
    try {
      await logoutHumanSession();
    } catch {
      setError("退出失败，请刷新页面确认当前 Session。");
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <button type="button" disabled={pending} onClick={() => void logout()}>
        {pending ? "正在退出…" : "退出登录"}
      </button>
      {error && <p role="alert">{error}</p>}
    </>
  );
}
