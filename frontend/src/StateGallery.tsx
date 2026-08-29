import { Card, Empty, Skeleton } from "antd";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Brand } from "./components/Brand";
import { StatusNotice } from "./components/SystemState";
import { ROUTES } from "./workspaceRegistry";

export function StateGallery() {
  return (
    <div className="state-gallery-page">
      <header className="state-gallery-topbar">
        <Brand audience="system" className="state-gallery-brand" to={ROUTES.states} />
        <nav aria-label="状态画廊导航" className="state-gallery-nav">
          <Link aria-current="page" to={ROUTES.states}>
            状态画廊
          </Link>
          <Link to={ROUTES.forbidden}>403 页面</Link>
          <Link to={ROUTES.notFound}>404 页面</Link>
        </nav>
      </header>

      <main className="state-gallery-content">
        <header className="state-gallery-intro">
          <div>
            <p className="eyebrow">系统状态</p>
            <h1>关键状态组件画廊</h1>
            <p>
              为加载、空、错误、实时连接与高风险操作提供一致的可见反馈，帮助评审者在同一页面比较状态语言。
            </p>
          </div>
          <aside className="state-gallery-scope" aria-label="画廊范围说明">
            <span>静态评审界面</span>
            <strong>不读取、不写入业务数据</strong>
            <p>以下内容是固定展示状态，不代表真实队列、审批或操作结果。</p>
          </aside>
        </header>

        <section aria-label="全局状态示例" className="state-gallery-grid">
          <StateCard
            className="state-card-loading"
            guidance="保留页面骨架，避免布局跳动。"
            id="loading"
            kicker="加载 · 首次加载"
            title="首次加载骨架"
          >
            <div
              aria-busy="true"
              aria-label="正在加载示例"
              className="state-loading-preview"
              role="status"
            >
              <Skeleton
                active
                paragraph={{ rows: 3, width: ["100%", "82%", "64%"] }}
                title={{ width: "46%" }}
              />
            </div>
          </StateCard>

          <StateCard
            className="state-card-empty"
            guidance="说明原因，并保留明确的后续预期。"
            id="empty"
            kicker="空状态 · 空队列"
            title="暂无队列条目"
          >
            <div className="state-empty-preview">
              <Empty description="当前没有待处理工单（示例）" />
              <p>新的工作项会在权威状态同步后出现。</p>
            </div>
          </StateCard>

          <StateCard
            className="state-card-error"
            guidance="保留旧数据，并明确它可能已经过期。"
            id="stale-error"
            kicker="错误 · 保留旧数据"
            title="数据加载失败"
          >
            <StatusNotice role="alert" tone="danger">
              <StateNoticeCopy
                detail="仍保留上一次读取的数据；当前内容可能已过期。"
                title="队列刷新失败"
              />
            </StatusNotice>
            <div
              aria-label="仍保留的上一版队列数据示例"
              className="state-stale-data-preview"
            >
              <div className="state-stale-data-meta">
                <span>上一版投影 · 静态示例</span>
                <span>最后同步 10:42 · 可能已过期</span>
              </div>
              <strong>示例队列条目</strong>
              <span>当前仍显示上一版状态，等待权威数据恢复后再更新。</span>
            </div>
          </StateCard>

          <StateCard
            className="state-card-forbidden"
            guidance="不泄露业务数据，只解释当前身份边界。"
            id="forbidden"
            kicker="403 · 能力不足"
            title="当前身份无权访问此页面"
          >
            <StateCodePreview
              code="403"
              detail="系统不会向未授权身份加载受保护内容。"
              title="当前身份无权访问此页面"
            />
          </StateCard>

          <StateCard
            className="state-card-not-found"
            guidance="说明地址不可用，并提供安全的返回入口。"
            id="not-found"
            kicker="404 · 页面不存在"
            title="没有找到这个页面"
          >
            <StateCodePreview
              code="404"
              detail="请检查地址，或从安全入口重新开始。"
              title="没有找到这个页面"
            />
          </StateCard>

          <StateCard
            className="state-card-disconnected"
            guidance="停止暗示数据实时，允许用户了解数据新鲜度。"
            id="disconnected"
            kicker="连接 · 实时连接断开"
            title="实时连接已断开"
          >
            <StatusNotice role="status" tone="danger">
              <StateNoticeCopy
                detail="页面不会自动更新，当前数据可能已过期。"
                title="实时连接已断开"
              />
            </StatusNotice>
          </StateCard>

          <StateCard
            className="state-card-syncing"
            guidance="展示同步范围，避免用户重复操作。"
            id="syncing"
            kicker="同步 · 正在重新同步"
            title="正在重新同步"
          >
            <StatusNotice role="status" tone="busy">
              <StateNoticeCopy
                detail="正在核对权威状态与当前页面投影。"
                title="正在重新同步队列"
              />
            </StatusNotice>
          </StateCard>

          <StateCard
            className="state-card-lease"
            guidance="责任过期后立即移除证据和操作入口。"
            id="lease-expired"
            kicker="审批 · 审批租约过期"
            title="审批租约过期"
          >
            <StatusNotice role="status" tone="warning">
              <StateNoticeCopy
                detail="此提案已退回队列，请重新领取后再查看授权内容。"
                title="审批责任已过期"
              />
            </StatusNotice>
          </StateCard>

          <StateCard
            className="state-card-success"
            guidance="明确结果和下一步，但不制造真实业务成功。"
            id="success"
            kicker="操作 · 操作成功"
            title="操作成功"
          >
            <StatusNotice role="status" tone="success">
              <StateNoticeCopy
                detail="这里只展示成功反馈，不代表真实审批或补偿记录。"
                title="操作已完成（静态示例）"
              />
            </StatusNotice>
          </StateCard>

          <StateCard
            className="state-card-unknown"
            guidance="不要暗示失败，优先使用幂等查询确认最终状态。"
            id="unknown-result"
            kicker="操作 · 操作结果未知"
            title="操作结果未知"
          >
            <StatusNotice role="alert" tone="warning">
              <StateNoticeCopy
                detail="请不要重复提交，使用幂等查询确认最终状态。"
                title="暂时无法确认操作结果"
              />
            </StatusNotice>
          </StateCard>
        </section>
      </main>
    </div>
  );
}

function StateCard({
  children,
  className,
  guidance,
  id,
  kicker,
  title,
}: {
  children: ReactNode;
  className: string;
  guidance: string;
  id: string;
  kicker: string;
  title: string;
}) {
  return (
    <Card bordered className={`state-gallery-card ${className}`}>
      <article aria-labelledby={`state-card-${id}`}>
        <header className="state-card-heading">
          <p className="state-card-kicker">{kicker}</p>
          <h2 id={`state-card-${id}`}>{title}</h2>
          <p>{guidance}</p>
        </header>
        <div className="state-card-preview">{children}</div>
      </article>
    </Card>
  );
}

function StateCodePreview({
  code,
  detail,
  title,
}: {
  code: string;
  detail: string;
  title: string;
}) {
  return (
    <div className="state-code-preview">
      <span aria-hidden="true" className="state-preview-code">
        {code}
      </span>
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

function StateNoticeCopy({ detail, title }: { detail: string; title: string }) {
  return (
    <span className="state-notice-copy">
      <strong>{title}</strong>
      <span>{detail}</span>
    </span>
  );
}
