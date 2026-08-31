import { useEffect, useState } from "react";

export type AutoResolution = {
  status: "PENDING" | "CANCELLED" | "REEVALUATING" | "RESOLVED";
  dueAt: string | null;
};

export function AutoResolutionNotice({
  resolution,
  cancelling,
  onCancel,
}: {
  resolution: AutoResolution;
  cancelling: boolean;
  onCancel: () => void;
}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (resolution.status !== "PENDING") return;
    const timer = globalThis.setInterval(() => setNow(Date.now()), 1_000);
    return () => globalThis.clearInterval(timer);
  }, [resolution.status, resolution.dueAt]);

  const seconds = resolution.dueAt
    ? Math.max(0, Math.ceil((Date.parse(resolution.dueAt) - now) / 1_000))
    : 0;
  const pending = resolution.status === "PENDING";
  const title =
    resolution.status === "PENDING"
      ? seconds > 0
        ? "即将自动解决"
        : "正在重新核验"
      : {
          CANCELLED: "已取消自动解决",
          REEVALUATING: "正在重新评估",
          RESOLVED: "工单已自动解决",
        }[resolution.status];

  return (
    <section className="auto-resolution-notice" aria-label="自动解决状态">
      <div>
        <strong role="status">{title}</strong>
        {pending && seconds > 0 ? (
          <>
            <p>
              距离服务端重新核验还剩{" "}
              <span role="timer" aria-live="off">
                {Math.floor(seconds / 60)} 分 {seconds % 60} 秒
              </span>
              。只有核验通过后才会自动解决。
            </p>
            <p className="auto-resolution-deadline">
              预计核验时间：
              <time dateTime={resolution.dueAt ?? undefined}>
                {new Date(resolution.dueAt ?? "").toLocaleString("zh-CN")}
              </time>
              。刷新页面不会重新计时。
            </p>
          </>
        ) : (
          <p>
            {pending
              ? "倒计时已结束，正在等待服务端核验结果；工单尚未因此自动解决。"
              : resolution.status === "CANCELLED"
                ? "本次自动解决已取消，工单会按最新状态继续处理。"
                : resolution.status === "REEVALUATING"
                  ? "当前条件已变化，自动解决已停止。请继续回复，以便重新评估。"
                  : "服务端已确认本次问题解决。如仍有问题，可使用下方回复入口。"}
          </p>
        )}
      </div>
      {pending && (
        <button type="button" disabled={cancelling} onClick={onCancel}>
          {cancelling ? "正在提交…" : "仍需帮助，取消自动解决"}
        </button>
      )}
    </section>
  );
}
