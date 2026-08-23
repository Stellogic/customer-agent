import { Alert, Result, Skeleton, Spin } from "antd";
import type { ReactNode } from "react";

type SystemStateProps = {
  eyebrow: string;
  title: string;
  description: string;
  variant: "loading" | "error" | "forbidden" | "not-found";
  code?: "403" | "404";
  busy?: boolean;
  announcement?: "status" | "alert";
  announcementLabel?: string;
  actions?: ReactNode;
};

export function SystemState({
  eyebrow,
  title,
  description,
  variant,
  code,
  busy = false,
  announcement,
  announcementLabel,
  actions,
}: SystemStateProps) {
  const stateIconLabel =
    variant === "error" ? "身份确认失败" : variant === "forbidden" ? "禁止访问" : "页面未找到";
  const stateGlyph = variant === "error" ? "!" : variant === "forbidden" ? "⊘" : "?";
  const descriptionNode = (
    <p role={announcement} aria-label={announcementLabel}>
      {description}
    </p>
  );

  return (
    <main className={`route-state route-state-${variant}`} aria-busy={busy || undefined}>
      <p className="eyebrow">{eyebrow}</p>
      {variant === "loading" ? (
        <>
          <span className="route-state-spinner" role="img" aria-label="正在加载身份">
            <Spin size="large" />
          </span>
          <h1>{title}</h1>
          {descriptionNode}
          <Skeleton
            className="route-state-skeleton"
            active
            paragraph={{ rows: 2, width: ["100%", "76%"] }}
            title={{ width: "48%" }}
          />
        </>
      ) : (
        <>
          <span className="route-state-glyph" role="img" aria-label={stateIconLabel}>
            {stateGlyph}
          </span>
          <Result
            className="route-state-result"
            status={code ?? "error"}
            icon={null}
            title={
              <>
                {code && <span className="route-state-code">{code}</span>}
                <h1>{title}</h1>
              </>
            }
            subTitle={descriptionNode}
            extra={actions && <div className="route-state-actions">{actions}</div>}
          />
        </>
      )}
    </main>
  );
}

export function StatusNotice({
  children,
  tone = "neutral",
  role = "status",
  className = "",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "busy" | "warning" | "danger";
  role?: "status" | "alert";
  className?: string;
}) {
  const type =
    tone === "success"
      ? "success"
      : tone === "warning"
        ? "warning"
        : tone === "danger"
          ? "error"
          : "info";

  return (
    <Alert
      className={`status-notice ${className}`.trim()}
      type={type}
      showIcon
      icon={tone === "busy" ? <Spin size="small" /> : undefined}
      title={children}
      role={role}
    />
  );
}
